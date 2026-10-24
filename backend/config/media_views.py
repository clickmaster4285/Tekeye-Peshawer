"""Serve /media/ only to logged-in users (token header or auth cookie)."""

from __future__ import annotations

import mimetypes
import os
import posixpath
import re

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve
from urllib.parse import quote

MEDIA_AUTH_COOKIE = "tekeye_auth_token"


def attach_media_auth_cookie(response: HttpResponse, token_key: str, request=None) -> HttpResponse:
    """Allow same-origin <img> / new-tab requests to send the API token.

    HttpOnly: page scripts cannot read it, so an injected script cannot steal it.
    """
    response.set_cookie(
        MEDIA_AUTH_COOKIE,
        token_key,
        httponly=True,
        samesite="Lax",
        path="/",
        secure=bool(request and request.is_secure()),
    )
    return response


def clear_media_auth_cookie(response: HttpResponse) -> HttpResponse:
    response.delete_cookie(MEDIA_AUTH_COOKIE, path="/", samesite="Lax")
    return response


def _token_key_from_request(request) -> str:
    auth = (request.META.get("HTTP_AUTHORIZATION") or "").strip()
    if auth.lower().startswith("token "):
        return auth[6:].strip()
    return (request.COOKIES.get(MEDIA_AUTH_COOKIE) or "").strip()


def media_user_from_request(request):
    key = _token_key_from_request(request)
    if not key:
        return None
    from users.token_auth import user_for_token_key

    return user_for_token_key(key)


def _safe_media_next(path: str) -> str | None:
    value = (path or "").strip()
    if not value.startswith("/media/"):
        return None
    if value.startswith("//") or "\\" in value or "://" in value:
        return None
    return value


def _login_redirect(request) -> HttpResponseRedirect:
    next_path = _safe_media_next(request.get_full_path() or "") or "/media/"
    from django.conf import settings

    frontend = getattr(settings, "FRONTEND_ORIGIN", "").rstrip("/") or ""
    login_base = f"{frontend}/login" if frontend else "/login"
    return HttpResponseRedirect(login_base + "?next=" + quote(next_path, safe="/"))


def _unauthorized(request) -> HttpResponse:
    accept = (request.headers.get("Accept") or "").lower()
    if "text/html" in accept:
        return _login_redirect(request)
    return HttpResponse("Authentication required", status=401, content_type="text/plain")


# Staff documents (CNIC, contracts, CVs) and face-training images: only for the
# people who may use the HR / recognition APIs that hand out these URLs.
HR_ONLY_MEDIA_PREFIXES = ("staff_docs/", "dataset/", "face_samples/")


def media_path_allowed(user, path: str) -> bool:
    from users.permissions import has_hr_api_access

    # Same normalising as django.views.static.serve, so "a/../staff_docs/x" is caught.
    clean = posixpath.normpath(path.replace("\\", "/")).lstrip("/").lower()
    if clean.startswith("hq_sync_media/"):
        # HQ keeps city files by date; the city's own path tells what the file is.
        from city_sync.models import HqMediaObject

        name = posixpath.basename(clean)
        source = (
            HqMediaObject.objects.filter(storage_path__iendswith=name)
            .values_list("source_path", flat=True)
            .first()
        )
        source = "/" + (source or "").replace("\\", "/").lower()
        if any("/" + prefix in source for prefix in HR_ONLY_MEDIA_PREFIXES):
            return has_hr_api_access(user)
        return True
    if clean.startswith(HR_ONLY_MEDIA_PREFIXES):
        return has_hr_api_access(user)
    return True


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _iter_file_range(fh, start: int, length: int, chunk: int = 64 * 1024):
    try:
        fh.seek(start)
        left = length
        while left > 0:
            data = fh.read(min(chunk, left))
            if not data:
                break
            left -= len(data)
            yield data
    finally:
        fh.close()


def _range_response(request, path: str) -> HttpResponse | None:
    """206 partial content for a single "Range: bytes=a-b" (video seeking). None = serve normally."""
    match = _RANGE_RE.match((request.META.get("HTTP_RANGE") or "").strip())
    if not match:
        return None
    full = safe_join(settings.MEDIA_ROOT, path)
    if not os.path.isfile(full):
        return None
    size = os.path.getsize(full)
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if first == "":
        start, end = max(0, size - int(last)), size - 1  # "bytes=-500" = last 500 bytes
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    length = end - start + 1
    content_type = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if request.method == "HEAD":
        response = HttpResponse(status=206, content_type=content_type)
    else:
        response = StreamingHttpResponse(
            _iter_file_range(open(full, "rb"), start, length), status=206, content_type=content_type
        )
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Content-Length"] = str(length)
    return response


def protected_media(request, path: str):
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    user = media_user_from_request(request)
    if user is None:
        return _unauthorized(request)
    if not path or path.endswith("/"):
        raise Http404("Not found")
    if not media_path_allowed(user, path):
        return HttpResponse("Not allowed", status=403, content_type="text/plain")
    try:
        response = _range_response(request, path) or serve(request, path, document_root=settings.MEDIA_ROOT)
    except SuspiciousFileOperation:
        raise Http404("Not found")
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    # PDFs are previewed in an <iframe> on our own pages; other sites still cannot frame them.
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response
