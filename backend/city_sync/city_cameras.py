"""HQ: label city copies with the city's camera names (CityCamera, sent on the heartbeat)."""

from __future__ import annotations

from city_sync.models import CityCamera


def city_camera(location_code: str, origin_pk, cache: dict | None = None) -> CityCamera | None:
    """The city's camera by its id there; `cache` (e.g. serializer context) avoids repeat queries."""
    try:
        pk = int(origin_pk)
    except (TypeError, ValueError):
        return None
    key = (location_code or "", pk)
    if cache is not None and key in cache:
        return cache[key]
    cam = CityCamera.objects.filter(location_code=key[0], origin_pk=pk).first()
    if cache is not None:
        cache[key] = cam
    return cam


def cache_for(context: dict | None) -> dict | None:
    """One lookup cache per serializer call (lists share it across rows)."""
    if context is None:
        return None
    return context.setdefault("_city_cameras", {})
