"""go2rtc client — register RTSP streams and exchange WebRTC SDP (viewing path)."""

from __future__ import annotations

import logging
from urllib.parse import quote, urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def go2rtc_configured() -> bool:
    return bool((getattr(settings, "GO2RTC_URL", "") or "").strip())


def go2rtc_base() -> str:
    return (getattr(settings, "GO2RTC_URL", "") or "").strip().rstrip("/")


def stream_name_for(server_id: int | None, stream_key: str) -> str:
    key = (stream_key or "").strip().replace("/", "_")
    if server_id is None:
        return key
    return f"s{server_id}_{key}"


def _webrtc_source(rtsp_url: str) -> str:
    """
    NVR cameras are H.265; Chrome WebRTC needs H.264.
    go2rtc ffmpeg source transcodes. Avoid #hardware (hangs often on Windows).
    """
    mode = (getattr(settings, "GO2RTC_VIDEO_MODE", "h264") or "h264").strip().lower()
    rtsp = (rtsp_url or "").strip()
    if not rtsp:
        return ""
    if mode in ("copy", "hevc", "h265", "passthrough"):
        return rtsp
    return f"ffmpeg:{rtsp}#video=h264#audio=copy"


def ensure_stream(name: str, rtsp_url: str) -> bool:
    """Register or refresh a named stream on go2rtc. Returns False if go2rtc unreachable."""
    base = go2rtc_base()
    src = _webrtc_source(rtsp_url)
    if not base or not name or not src:
        return False

    # quote() encodes '#' → %23 so go2rtc receives the full ffmpeg options
    url = f"{base}/api/streams?name={quote(name, safe='')}&src={quote(src, safe='')}"
    try:
        res = requests.put(url, timeout=8)
        # go2rtc may return 200 with body, or 400 yaml noise while still registering
        check = requests.get(f"{base}/api/streams", timeout=5)
        streams = check.json() if check.ok else {}
        if name in streams:
            return True
        if res.status_code in (200, 201, 204):
            return True
        logger.warning(
            "go2rtc ensure_stream %s → HTTP %s %s",
            name,
            res.status_code,
            (res.text or "")[:200],
        )
        return False
    except requests.RequestException as exc:
        logger.warning("go2rtc ensure_stream failed: %s", exc)
        return False


def warm_stream(name: str, *, timeout: float = 20.0) -> bool:
    """Pull one JPEG so go2rtc starts ffmpeg/RTSP before WebRTC SDP (avoids client timeout)."""
    base = go2rtc_base()
    if not base or not name:
        return False
    try:
        res = requests.get(
            f"{base}/api/frame.jpeg",
            params={"src": name},
            timeout=timeout,
        )
        return res.status_code == 200 and len(res.content or b"") > 1000
    except requests.RequestException as exc:
        logger.warning("go2rtc warm_stream %s failed: %s", name, exc)
        return False


def exchange_webrtc_sdp(name: str, offer_sdp: str) -> tuple[str | None, str]:
    """
    POST browser SDP offer to go2rtc; return (answer_sdp, error).
    go2rtc returns 200 or 201 with application/sdp body.
    """
    base = go2rtc_base()
    if not base:
        return None, "GO2RTC_URL is not configured."
    if not name:
        return None, "stream name required."
    if not (offer_sdp or "").strip():
        return None, "SDP offer required."

    url = urljoin(base + "/", f"api/webrtc?src={quote(name)}")
    try:
        res = requests.post(
            url,
            data=offer_sdp.encode("utf-8"),
            headers={"Content-Type": "application/sdp"},
            timeout=25,
        )
        answer = (res.text or "").strip()
        # Success: 200/201 with SDP (starts with v=0)
        if res.status_code in (200, 201) and answer.startswith("v="):
            return answer, ""
        if res.status_code in (200, 201) and "v=0" in answer:
            idx = answer.find("v=0")
            return answer[idx:], ""
        return None, f"go2rtc WebRTC HTTP {res.status_code}: {answer[:300]}"
    except requests.RequestException as exc:
        return None, str(exc)


def health_ok() -> bool:
    base = go2rtc_base()
    if not base:
        return False
    try:
        res = requests.get(f"{base}/api", timeout=3)
        return res.status_code == 200
    except requests.RequestException:
        return False
