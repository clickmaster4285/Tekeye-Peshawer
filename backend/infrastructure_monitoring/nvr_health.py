"""NVR health probing — channels & logs from the NVR (ISAPI / Dahua), not TekEye cameras."""

from __future__ import annotations

import logging
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from xml.etree.ElementTree import Element

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

logger = logging.getLogger(__name__)

# Suppress insecure-request warnings for LAN NVRs with self-signed certs / plain HTTP
try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


def _tag(el: Element) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _find_text(root: Element, *names: str) -> str:
    # Prefer names in the order given (not document order).
    for name in names:
        want = name.lower()
        for el in root.iter():
            if _tag(el).lower() == want and el.text and el.text.strip():
                return el.text.strip()
    return ""


def _find_direct(parent: Element, *names: str) -> str:
    for name in names:
        want = name.lower()
        for child in list(parent):
            if _tag(child).lower() == want and child.text and child.text.strip():
                return child.text.strip()
    return ""


def _http_request(
    method: str,
    ip: str,
    path: str,
    *,
    username: str,
    password: str,
    port: int = 80,
    timeout: float = 8.0,
    data: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    url = f"http://{ip}:{port}{path}"
    hdrs = {"Content-Type": "application/xml"} if data else {}
    if headers:
        hdrs.update(headers)
    auths = []
    if username:
        auths.append(HTTPDigestAuth(username, password or ""))
        auths.append(HTTPBasicAuth(username, password or ""))
    else:
        auths.append(None)

    last_err = ""
    for auth in auths:
        try:
            res = requests.request(
                method,
                url,
                auth=auth,
                data=data,
                headers=hdrs or None,
                timeout=timeout,
                verify=False,
            )
            # Retry with other auth if unauthorized
            if res.status_code == 401 and auth is not None:
                last_err = "401 unauthorized"
                continue
            return res.status_code, res.text or ""
        except Exception as exc:
            last_err = str(exc)
            logger.debug("NVR HTTP %s %s failed: %s", method, url, exc)
    return None, last_err


def _http_get(ip: str, path: str, **kwargs) -> tuple[int | None, str]:
    return _http_request("GET", ip, path, **kwargs)


def _http_post(ip: str, path: str, data: str, **kwargs) -> tuple[int | None, str]:
    return _http_request("POST", ip, path, data=data, **kwargs)


def _http_put(ip: str, path: str, data: str | None = None, **kwargs) -> tuple[int | None, str]:
    return _http_request("PUT", ip, path, data=data, **kwargs)


def resolve_cameras_nvr_id(device) -> int | None:
    """Map InfraDevice → cameras.Nvr id (source_key or IP match)."""
    sk = (getattr(device, "source_key", None) or "").strip()
    if sk.startswith("cameras.nvr:"):
        try:
            return int(sk.split(":", 1)[1])
        except (TypeError, ValueError):
            pass
    ip = (getattr(device, "ip_address", None) or "").strip()
    if not ip:
        return None
    try:
        from cameras.models import Nvr

        nvr = (
            Nvr.objects.filter(ip_address=ip, is_active=True)
            .order_by("id")
            .first()
        )
        return int(nvr.id) if nvr else None
    except Exception:
        return None


def _nvr_http_creds(device) -> tuple[str, str, str, int]:
    ip = (device.ip_address or "").strip()
    username = (device.username or "").strip()
    password = device.password or ""
    http_port = int(device.onvif_port or 80)
    return ip, username, password, http_port


def execute_nvr_command(
    device,
    action: str,
    *,
    disk_id: str | int | None = None,
    channel: str | int | None = None,
) -> dict[str, Any]:
    """
    Execute a write/control action against the NVR over ISAPI / Dahua CGI.
    Returns { ok, action, message, http_status?, detail? }.
    """
    action = (action or "").strip().lower().replace("-", "_")
    ip, username, password, http_port = _nvr_http_creds(device)
    if not ip:
        return {"ok": False, "action": action, "message": "NVR has no IP address"}
    if not username:
        return {"ok": False, "action": action, "message": "NVR username/password required"}

    brand = (device.manufacturer or device.model_number or "").lower()

    # —— Read-only diagnostics (always available) ——
    if action in ("diagnostics", "run_diagnostics", "refresh_status"):
        metrics = enrich_nvr_metrics(device)
        return {
            "ok": True,
            "action": action,
            "message": "Diagnostics complete — health refreshed from NVR",
            "summary": {
                "hdd_status": metrics.get("hdd_status"),
                "channels_total": (metrics.get("channels") or {}).get("total"),
                "channels_online": (metrics.get("channels") or {}).get("online"),
                "network": metrics.get("network_interface_status"),
                "nvr_status": metrics.get("nvr_status"),
            },
        }

    if action in ("test_network",):
        net = (
            fetch_dahua_network(ip, username=username, password=password, http_port=http_port)
            if "dahua" in brand
            else fetch_hikvision_network(
                ip, username=username, password=password, http_port=http_port
            )
        )
        return {
            "ok": bool(net.get("network_ok")),
            "action": action,
            "message": "Network probe finished",
            "result": net,
        }

    if action in ("test_storage",):
        storage = fetch_hikvision_storage(
            ip, username=username, password=password, http_port=http_port
        )
        return {
            "ok": bool(storage.get("storage_ok")),
            "action": action,
            "message": "Storage probe finished",
            "result": {
                "hdd_status": storage.get("hdd_status"),
                "hdd_count": storage.get("hdd_count"),
                "free_mb": storage.get("hdd_free_mb"),
                "capacity_mb": storage.get("hdd_capacity_mb"),
            },
        }

    # —— Reboot ——
    if action in ("reboot", "restart", "restart_nvr"):
        if "dahua" in brand:
            code, body = _http_get(
                ip,
                "/cgi-bin/magicBox.cgi?action=reboot",
                username=username,
                password=password,
                port=http_port,
                timeout=15,
            )
        else:
            reboot_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Reboot xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0"></Reboot>'
            )
            code, body = None, ""
            for path, payload in (
                ("/ISAPI/System/reboot", reboot_xml),
                ("/ISAPI/System/reboot", None),
                ("/ISAPI/System/reboot?format=json", '{"Reboot":{}}'),
            ):
                code, body = _http_request(
                    "PUT",
                    ip,
                    path,
                    username=username,
                    password=password,
                    port=http_port,
                    timeout=20,
                    data=payload,
                    headers={"Content-Type": "application/json"}
                    if payload and "json" in path
                    else None,
                )
                if code in (200, 201, 202, 204):
                    break
        ok = code in (200, 201, 202, 204) or (code is None and "timeout" in (body or "").lower())
        # Many NVRs drop connection mid-reboot — treat connection errors as accepted
        if code is None and body:
            ok = True
        return {
            "ok": ok,
            "action": "reboot",
            "message": "Reboot command sent to NVR" if ok else f"Reboot failed (HTTP {code})",
            "http_status": code,
            "detail": (body or "")[:300],
        }

    # —— Sync time ——
    if action in ("sync_time",):
        now = datetime.now(timezone.utc).astimezone()
        local = now.strftime("%Y-%m-%dT%H:%M:%S")
        # Hikvision Time XML
        time_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Time xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">'
            f"<localTime>{local}</localTime>"
            "<timeMode>manual</timeMode>"
            "</Time>"
        )
        code, body = _http_put(
            ip,
            "/ISAPI/System/time",
            time_xml,
            username=username,
            password=password,
            port=http_port,
            timeout=12,
        )
        if code not in (200, 201, 204) and "dahua" in brand:
            code, body = _http_get(
                ip,
                f"/cgi-bin/global.cgi?action=setCurrentTime&time={quote(local)}",
                username=username,
                password=password,
                port=http_port,
                timeout=12,
            )
        ok = code in (200, 201, 204)
        return {
            "ok": ok,
            "action": "sync_time",
            "message": f"NVR time set to {local}" if ok else f"Sync time failed (HTTP {code})",
            "http_status": code,
            "detail": (body or "")[:300],
        }

    # —— Format HDD ——
    if action in ("format_hdd", "format"):
        if disk_id in (None, "", "all"):
            return {
                "ok": False,
                "action": action,
                "message": "disk_id is required for format_hdd",
            }
        did = str(disk_id).strip()
        format_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<formatProgress xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">'
            f"<hdd id=\"{did}\"/>"
            "</formatProgress>"
        )
        code, body = None, ""
        for path, method, payload in (
            (f"/ISAPI/ContentMgmt/Storage/hdd/{did}/format", "PUT", None),
            (f"/ISAPI/ContentMgmt/Storage/hdd/{did}/format", "PUT", format_xml),
            ("/ISAPI/ContentMgmt/Storage/hdd/format", "PUT", format_xml),
        ):
            code, body = _http_request(
                method,
                ip,
                path,
                username=username,
                password=password,
                port=http_port,
                timeout=60,
                data=payload,
            )
            if code in (200, 201, 202, 204):
                break
        ok = code in (200, 201, 202, 204)
        return {
            "ok": ok,
            "action": "format_hdd",
            "message": f"Format started for HDD {did}" if ok else f"Format failed (HTTP {code})",
            "http_status": code,
            "detail": (body or "")[:400],
            "disk_id": did,
        }

    # —— Manual recording start/stop ——
    if action in ("start_recording", "stop_recording"):
        if channel in (None, ""):
            return {"ok": False, "action": action, "message": "channel is required"}
        try:
            ch = int(str(channel).strip())
        except ValueError:
            return {"ok": False, "action": action, "message": "Invalid channel"}
        track_id = ch if ch >= 100 else ch * 100 + 1
        verb = "start" if action == "start_recording" else "stop"
        paths = [
            f"/ISAPI/ContentMgmt/record/control/manual/{verb}/tracks/{track_id}",
            f"/ISAPI/ContentMgmt/record/control/manual/{verb}/channels/{ch}",
        ]
        code, body = None, ""
        for path in paths:
            code, body = _http_put(
                ip,
                path,
                None,
                username=username,
                password=password,
                port=http_port,
                timeout=12,
            )
            if code in (200, 201, 204):
                break
        ok = code in (200, 201, 204)
        return {
            "ok": ok,
            "action": action,
            "message": (
                f"Recording {verb} on channel {ch}"
                if ok
                else f"Recording {verb} failed (HTTP {code}) — firmware may not support manual control"
            ),
            "http_status": code,
            "detail": (body or "")[:300],
            "channel": ch,
            "track_id": track_id,
        }

    return {
        "ok": False,
        "action": action,
        "message": f"Unsupported action: {action}",
    }


def fetch_channel_snapshot_jpeg(
    device, channel: int
) -> tuple[bytes | None, str]:
    """Pull a JPEG snapshot from the NVR for a logical channel (1-based)."""
    ip, username, password, http_port = _nvr_http_creds(device)
    if not ip or not username:
        return None, "NVR credentials required"
    ch = max(1, int(channel))
    stream_id = ch if ch >= 100 else ch * 100 + 1
    paths = [
        f"/ISAPI/Streaming/channels/{stream_id}/picture",
        f"/ISAPI/Streaming/channels/{ch}/picture",
        f"/ISAPI/ContentMgmt/StreamingProxy/channels/{stream_id}/picture",
    ]
    url_base = f"http://{ip}:{http_port}"
    for path in paths:
        for auth in (
            HTTPDigestAuth(username, password or ""),
            HTTPBasicAuth(username, password or ""),
        ):
            try:
                res = requests.get(
                    f"{url_base}{path}",
                    auth=auth,
                    timeout=12,
                    verify=False,
                    headers={"Accept": "image/jpeg"},
                )
                if res.status_code == 401:
                    continue
                ctype = (res.headers.get("Content-Type") or "").lower()
                if res.status_code == 200 and (
                    "image" in ctype or res.content[:3] == b"\xff\xd8\xff"
                ):
                    return res.content, ""
            except Exception as exc:
                logger.debug("snapshot %s failed: %s", path, exc)
    return None, "Snapshot not available from this NVR firmware"


def _safe_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_kv(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (body or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _truthy(val: str) -> bool:
    return val.strip().lower() in ("1", "true", "yes", "online", "ok", "normal", "connected")


def _channel_state_from_flags(*, online: bool, video_loss: bool) -> str:
    if video_loss:
        return "video_loss"
    if online:
        return "online"
    return "offline"


# Canonical HDD statuses — match Hikvision NVR Storage UI wording.
NVR_HDD_STATUS_LABELS = (
    "Normal",
    "Sleep",
    "Error",
    "Abnormal",
    "Offline",
    "Unformatted",
    "Full",
    "Unknown",
)


def map_nvr_hdd_status(raw_status: str, *, usage_pct: float | None = None) -> str:
    """Map vendor HDD status strings to the same labels shown on the NVR UI."""
    s = (raw_status or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")

    # Already a known label (from a previous normalize pass)
    titled = (raw_status or "").strip().title()
    if titled in NVR_HDD_STATUS_LABELS:
        return titled
    # Title-case "sleep" → "Sleep"
    if titled == "Sleep":
        return "Sleep"

    if not s or s in ("unknown", "na", "n/a", "none"):
        return "Unknown"

    # Trust vendor ok/normal — freeSpace=0 with status ok is still Normal on NVR UI
    if s in ("ok", "normal", "good", "healthy", "fine", "ready"):
        return "Normal"

    # Hikvision idle ↔ NVR UI "Sleep"
    if s in ("sleep", "sleeping", "idle", "standby"):
        return "Sleep"

    if s in ("full", "spacefull", "diskfull", "hddfull"):
        return "Full"

    if s in ("offline", "notexist", "missing", "nodisk", "unused", "empty"):
        return "Offline"

    if "unformat" in s or s in ("raw", "notformatted"):
        return "Unformatted"

    if s in ("error", "err", "fault", "failed", "fail", "bad", "damage", "damaged"):
        return "Error"

    if s in ("abnormal", "warning", "warn", "degraded", "busy"):
        return "Abnormal"

    if "error" in s or "fault" in s or "fail" in s:
        return "Error"
    if "sleep" in s or s == "idle":
        return "Sleep"
    if "abnormal" in s or "warn" in s:
        return "Abnormal"
    if "offline" in s or "missing" in s:
        return "Offline"
    if "unformat" in s:
        return "Unformatted"
    if "full" in s:
        return "Full"

    return "Unknown"


def hdd_status_level(label: str) -> str:
    """healthy | warning | critical | unknown for health engine / UI colors."""
    # Sleep is a normal NVR state (disk spun down) — not a fault.
    if label in ("Normal", "Sleep"):
        return "healthy"
    if label == "Full":
        return "warning"
    if label in ("Error", "Abnormal", "Offline", "Unformatted"):
        return "critical"
    return "unknown"


def _mb_to_display(mb: Any) -> str:
    """Display capacity like the NVR UI (GB for multi-TB disks, not forced TiB)."""
    try:
        v = float(mb)
    except (TypeError, ValueError):
        return "—"
    if v < 0:
        return "—"
    if v == 0:
        return "0 GB"
    # NVR Storage page uses Capacity(GB) / Remaining Capacity(GB) ≈ MB/1024
    if v >= 1024:
        gb = v / 1024.0
        if gb >= 100:
            return f"{gb:.0f} GB"
        return f"{gb:.2f} GB"
    return f"{v:.0f} MB"


def _optional_mb(raw: dict[str, Any], *keys: str) -> float | None:
    """Read a capacity/free value only when the key is present (missing ≠ 0)."""
    for key in keys:
        if key not in raw:
            continue
        val = raw.get(key)
        if val is None or val == "":
            return None
        parsed = _safe_float(val)
        if parsed is not None:
            return parsed
    return None


def normalize_hdd_entry(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """Normalize one HDD into a UI-ready dict (works for fresh ISAPI or stored metrics)."""
    raw_status = str(raw.get("status") or raw.get("hddStatus") or "unknown").strip() or "unknown"
    cap = _optional_mb(raw, "capacity_mb", "capacity", "hddCapacity") or 0.0
    free = _optional_mb(raw, "free_mb", "freeSpace", "hddFreeSpace", "free")
    used = _optional_mb(raw, "used_mb", "used")
    free_known = free is not None
    if used is None and free_known and cap > 0:
        used = max(0.0, cap - float(free))
    usage_pct = (
        round((float(used) / cap) * 100.0, 1)
        if used is not None and cap > 0
        else None
    )
    # Only treat as Full when free space was actually reported as ~0
    if free_known and free is not None and cap > 0 and free <= max(1.0, cap * 0.005):
        if usage_pct is None:
            usage_pct = 100.0
        if used is None:
            used = max(0.0, cap - float(free))

    disk_no = raw.get("disk_number") or raw.get("id") or raw.get("hddName") or (index + 1)
    try:
        disk_number = int(str(disk_no).strip())
    except (TypeError, ValueError):
        disk_number = index + 1

    disk_type = str(raw.get("disk_type") or raw.get("hddType") or raw.get("type") or "").strip()
    disk_model = str(raw.get("disk_model") or raw.get("hddModel") or "").strip()
    disk_serial = str(
        raw.get("disk_serial") or raw.get("hddSerialNumber") or raw.get("serial") or ""
    ).strip()
    attribute = str(raw.get("attribute") or "").strip()
    if not attribute:
        prop = str(raw.get("property") or "").strip().upper()
        attribute = {"RW": "R/W", "RO": "R/O", "REDUND": "Redundant"}.get(prop, prop)
    # Vendor status wins. Only label Full when NVR explicitly says full.
    health_label = map_nvr_hdd_status(raw_status, usage_pct=None)
    if health_label == "Unknown" and raw_status.strip().lower() in ("full",):
        health_label = "Full"

    level = hdd_status_level(health_label)
    free_mb = float(free) if free_known and free is not None else None
    used_mb = float(used) if used is not None else None
    # Remaining capacity in GB (same unit as NVR Storage → Remaining Capacity(GB))
    remaining_gb = round(free_mb / 1024.0) if free_mb is not None else None
    capacity_gb = round(cap / 1024.0) if cap > 0 else None

    return {
        "disk_number": disk_number,
        "name": f"HDD {disk_number}",
        "status": health_label,  # exact NVR status label
        "raw_status": raw_status,
        "health_label": health_label,
        "level": level,
        "capacity_mb": cap,
        "free_mb": free_mb,
        "used_mb": used_mb,
        "capacity_gb": capacity_gb,
        "remaining_gb": remaining_gb,
        "usage_pct": usage_pct if free_known else None,
        "free_known": free_known,
        "capacity_display": _mb_to_display(cap) if cap > 0 else "—",
        "free_display": _mb_to_display(free_mb) if free_known else "—",
        "used_display": _mb_to_display(used_mb) if used_mb is not None else "—",
        "usage_display": (
            f"{usage_pct:.1f}%" if free_known and usage_pct is not None else "—"
        ),
        "disk_type": disk_type or "—",
        "attribute": attribute or "—",
        "disk_model": disk_model or "—",
        "disk_serial": disk_serial or "—",
        "error_status": "None" if health_label in ("Normal", "Sleep") else health_label,
    }


def normalize_hdd_list(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        out.append(normalize_hdd_entry(row, i))
    out.sort(key=lambda r: int(r.get("disk_number") or 0))
    return out


def _rank_level(level: str) -> int:
    return {"healthy": 0, "warning": 1, "critical": 2, "unknown": -1}.get(
        (level or "").lower(), -1
    )


def _worst_level(*levels: str) -> str:
    best = "unknown"
    best_rank = -1
    for lv in levels:
        r = _rank_level(lv)
        if r > best_rank:
            best = (lv or "unknown").lower()
            best_rank = r
    return best if best_rank >= 0 else "unknown"


def compute_nvr_health(metrics: dict[str, Any], *, device_status: str = "") -> dict[str, Any]:
    """
    Unified NVR health scorecard from polled metrics.
    Levels: healthy | warning | critical | unknown
    """
    hdds = normalize_hdd_list(metrics.get("hdd_list") if isinstance(metrics.get("hdd_list"), list) else [])
    channels = metrics.get("channels") if isinstance(metrics.get("channels"), dict) else {}
    total = int(channels.get("total") or 0)
    online = int(channels.get("online") or 0)
    offline = int(channels.get("offline") or 0)
    video_loss = int(channels.get("video_loss") or 0)
    recording = int(channels.get("recording") or 0)

    # Storage — Full (circular overwrite) is warning, not critical/abnormal
    if not hdds and not metrics.get("storage_ok"):
        storage_level = "unknown"
        storage_label = "No storage data"
        storage_detail = "Storage not reported"
    else:
        bad = sum(1 for h in hdds if h.get("level") == "critical")
        warn = sum(1 for h in hdds if h.get("level") == "warning")
        ok = sum(1 for h in hdds if h.get("level") == "healthy")
        full = sum(1 for h in hdds if h.get("health_label") == "Full")
        sleep = sum(1 for h in hdds if h.get("health_label") == "Sleep")
        if bad:
            storage_level = "critical"
            storage_label = f"{ok}/{len(hdds)} Healthy"
            storage_detail = f"{bad} disk(s) error/offline"
        elif warn:
            storage_level = "warning"
            storage_label = f"{ok}/{len(hdds)} Healthy"
            if sleep and sleep == warn:
                storage_detail = f"{sleep} disk(s) sleep"
            elif full and full == warn:
                storage_detail = f"{full} disk(s) full (overwrite mode)"
            else:
                storage_detail = f"{warn} disk(s) need attention"
        elif hdds:
            storage_level = "healthy"
            storage_label = f"{len(hdds)}/{len(hdds)} Healthy"
            storage_detail = "All disks normal"
        else:
            storage_level = "healthy" if metrics.get("hdd_status") in ("ok", "normal", "full") else "unknown"
            storage_label = str(metrics.get("hdd_status") or "Unknown")
            storage_detail = "Aggregated storage only"

    # Cameras
    problem = offline + video_loss
    if total <= 0:
        cameras_level = "unknown"
        cameras_label = "No channels"
        cameras_detail = "Channel list empty"
    elif problem == 0:
        cameras_level = "healthy"
        cameras_label = f"{online}/{total} Online"
        cameras_detail = "All channels online"
    elif problem / max(total, 1) >= 0.25 or online == 0:
        cameras_level = "critical"
        cameras_label = f"{online}/{total} Online"
        cameras_detail = f"{problem} offline/video-loss"
    else:
        cameras_level = "warning"
        cameras_label = f"{online}/{total} Online"
        cameras_detail = f"{problem} offline/video-loss"

    # Recording (Phase-1 heuristic — Phase 2 will add evidence age)
    rec_status = str(metrics.get("recording_status") or "").lower()
    if total <= 0:
        recording_level = "unknown"
        recording_label = "Unknown"
        recording_detail = "No channel data"
    elif online > 0 and recording == 0:
        recording_level = "critical"
        recording_label = "Recording stopped"
        recording_detail = f"0/{online} online cameras recording"
    elif online > 0 and recording < online:
        recording_level = "warning"
        recording_label = f"{recording}/{online} Recording"
        recording_detail = "Some online cameras not recording"
    elif recording > 0 or rec_status in ("available", "ok", "normal", "recording"):
        recording_level = "healthy"
        recording_label = "Active" if recording > 0 else "Available"
        recording_detail = f"{recording} channel(s) recording"
    else:
        recording_level = "unknown"
        recording_label = rec_status or "Unknown"
        recording_detail = "Recording status unclear"

    # System
    ds = (device_status or metrics.get("nvr_status") or "").lower()
    temp = _safe_float(metrics.get("temperature_c"))
    cpu = _safe_float(metrics.get("cpu_percent"))
    if "offline" in ds:
        system_level = "critical"
        system_label = "Offline"
        system_detail = "NVR unreachable"
    else:
        system_level = "healthy"
        system_label = "Normal"
        system_detail = "System OK"
        if temp is not None and temp >= 85:
            system_level = "critical"
            system_label = f"{temp:.0f}°C"
            system_detail = "Temperature critical"
        elif temp is not None and temp >= 70:
            system_level = "warning"
            system_label = f"{temp:.0f}°C"
            system_detail = "Temperature high"
        elif cpu is not None and cpu >= 95:
            system_level = "warning"
            system_label = f"CPU {cpu:.0f}%"
            system_detail = "CPU high"

    # Network — if we are polling the NVR successfully it cannot be hard-down
    iface = str(metrics.get("network_interface_status") or "").lower().strip()
    iface_up = iface in (
        "up",
        "connect",
        "connected",
        "linkup",
        "online",
        "ok",
        "normal",
    )
    iface_down = iface in ("down", "disconnect", "disconnected", "linkdown", "offline", "error", "fault")
    reachable = "online" in ds or bool(metrics.get("device_info_ok") or metrics.get("network_ok"))
    if "offline" in ds and not reachable:
        network_level = "critical"
        network_label = "Down"
        network_detail = "Device offline"
    elif iface_down and not reachable:
        network_level = "critical"
        network_label = "Down"
        network_detail = "Interface fault"
    elif iface_down and reachable:
        # Stale/wrong secondary NIC status while HTTP still works
        network_level = "healthy"
        network_label = "Connected"
        network_detail = metrics.get("network_link_speed") or "Reachable (link status ambiguous)"
    elif iface_up or reachable:
        network_level = "healthy"
        network_label = "Connected"
        network_detail = metrics.get("network_link_speed") or "Link up"
    else:
        network_level = "unknown"
        network_label = "Unknown"
        network_detail = "No network metrics"

    overall = _worst_level(
        storage_level, cameras_level, recording_level, system_level, network_level
    )
    overall_label = {
        "healthy": "Healthy",
        "warning": "Warning",
        "critical": "Critical",
        "unknown": "Unknown",
    }.get(overall, "Unknown")

    healthy_disks = sum(1 for h in hdds if h.get("level") == "healthy")
    return {
        "overall": overall,
        "overall_label": overall_label,
        "storage": {
            "level": storage_level,
            "label": storage_label,
            "detail": storage_detail,
            "disk_count": len(hdds),
            "healthy_disks": healthy_disks,
        },
        "cameras": {
            "level": cameras_level,
            "label": cameras_label,
            "detail": cameras_detail,
            "online": online,
            "total": total,
        },
        "recording": {
            "level": recording_level,
            "label": recording_label,
            "detail": recording_detail,
            "recording": recording,
            "online": online,
        },
        "system": {
            "level": system_level,
            "label": system_label,
            "detail": system_detail,
        },
        "network": {
            "level": network_level,
            "label": network_label,
            "detail": str(network_detail),
        },
    }


def _summarize_channels(items: list[dict[str, Any]]) -> dict[str, Any]:
    online = offline = video_loss = recording = 0
    for it in items:
        st = it.get("status") or "offline"
        if st == "online":
            online += 1
        elif st == "video_loss":
            video_loss += 1
        else:
            offline += 1
        if it.get("recording"):
            recording += 1
    return {
        "source": "nvr",
        "total": len(items),
        "online": online,
        "offline": offline,
        "video_loss": video_loss,
        "recording": recording,
        "items": items,
    }


def _format_link_speed(raw: Any) -> str:
    """Normalize NVR link speed to a human label (never show bare 0 as success)."""
    if raw is None or raw == "":
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    lower = s.lower().replace(" ", "")
    if lower in ("0", "0m", "0mbps", "0mb", "unknown", "n/a", "na", "-"):
        return ""
    # Already labeled
    if "mbps" in lower or "gbps" in lower or "mbit" in lower:
        return s
    try:
        val = float(s.replace(",", ""))
    except ValueError:
        return s
    if val <= 0:
        return ""
    if val >= 1000 and val % 1000 == 0:
        gb = val / 1000
        if gb == int(gb):
            return f"{int(gb)} Gbps"
        return f"{gb:g} Gbps"
    if val == int(val):
        return f"{int(val)} Mbps"
    return f"{val:g} Mbps"


def _format_bytes(raw: Any) -> str:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.2f} {units[i]}"


def _normalize_link_oper_status(raw: str) -> str:
    """Map Hikvision linkStatus values to up/down/unknown."""
    s = (raw or "").strip().lower().replace(" ", "").replace("_", "")
    if s in (
        "up",
        "connect",
        "connected",
        "linkup",
        "online",
        "ok",
        "normal",
        "true",
        "1",
        "active",
    ):
        return "up"
    if s in (
        "down",
        "disconnect",
        "disconnected",
        "linkdown",
        "offline",
        "false",
        "0",
        "inactive",
        "error",
        "fault",
    ):
        return "down"
    return ""


def fetch_hikvision_network(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> dict[str, Any]:
    """
    Parse NVR NIC status correctly.

    Hikvision XML often has:
      <NetworkInterface>
        <IPAddress><addressingType>static</addressingType>...</IPAddress>
        <Link><speed>1000</speed><duplex>full</duplex>...</Link>
      </NetworkInterface>

    We must NOT treat addressingType (static/dhcp) as interface status,
    and must NOT prefer a disabled secondary NIC that reports down/half.
    HTTP reachability implies the active management NIC is up.
    """
    out: dict[str, Any] = {}
    code, body = _http_get(
        ip,
        "/ISAPI/System/Network/interfaces",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            scored: list[tuple[int, dict[str, Any]]] = []
            for iface in root.iter():
                if _tag(iface).lower() != "networkinterface":
                    continue
                iface_id = _find_direct(iface, "id") or "1"
                enabled = _find_direct(iface, "enabled", "enable") or ""
                speed = ""
                duplex = ""
                mac = ""
                link_status = ""
                addressing = ""
                ip_addr = ""
                for child in list(iface):
                    t = _tag(child).lower()
                    if t == "link":
                        speed = (
                            _find_direct(child, "speed", "linkSpeed", "Speed")
                            or _find_text(child, "speed", "linkSpeed")
                        )
                        duplex = _find_direct(child, "duplex", "Duplex") or _find_text(
                            child, "duplex"
                        )
                        mac = _find_direct(child, "MACAddress", "macAddress") or _find_text(
                            child, "MACAddress", "macAddress"
                        )
                        # Never use bare "status" — overlaps unrelated nodes
                        link_status = _find_direct(
                            child, "linkStatus", "connectionStatus", "operStatus"
                        ) or _find_text(child, "linkStatus", "connectionStatus", "operStatus")
                    elif t == "ipaddress":
                        addressing = (
                            _find_direct(child, "addressingType", "ipAddressType")
                            or _find_text(child, "addressingType")
                        )
                        ip_addr = (
                            _find_direct(child, "ipAddress", "address", "ipv4Address")
                            or _find_text(child, "ipAddress", "ipv4Address")
                        )
                oper = _normalize_link_oper_status(link_status)
                en = (enabled or "").lower()
                enabled_yes = en in ("true", "1", "yes", "")
                enabled_no = en in ("false", "0", "no")
                speed_ok = bool(_format_link_speed(speed))
                score = 0
                if oper == "up":
                    score += 50
                if enabled_yes and not enabled_no:
                    score += 20
                if ip_addr:
                    score += 15
                # Prefer the NIC that matches the IP we are polling
                if ip_addr and ip_addr.strip() == str(ip).strip():
                    score += 100
                if addressing:
                    score += 5
                if speed_ok:
                    score += 10
                # enabled=false is common on Hikvision even for the active NIC — don't punish hard
                if oper == "down":
                    score -= 40
                candidate = {
                    "id": iface_id,
                    "enabled": enabled,
                    "speed": speed,
                    "duplex": duplex,
                    "mac": mac,
                    "link_status": link_status,
                    "oper": oper,
                    "addressing": addressing,
                    "ip": ip_addr,
                }
                scored.append((score, candidate))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                best = scored[0][1]
                oper = best.get("oper") or ""
                if not oper:
                    en = (best.get("enabled") or "").lower()
                    if en in ("false", "0", "no"):
                        oper = "down"
                    else:
                        # Management HTTP succeeded — active path is up
                        oper = "up"
                # If best score is still a down NIC but we got HTTP 200, force up
                if oper == "down":
                    oper = "up"
                out["network_interface_status"] = oper
                out["network_addressing"] = best.get("addressing") or ""
                out["network_mac"] = best.get("mac") or ""
                speed_label = _format_link_speed(best.get("speed"))
                duplex = (best.get("duplex") or "").strip()
                # Hikvision reports speed=0 + duplex=half when autoNegotiation is on;
                # that is NOT the real negotiated link — do not show "half duplex".
                if speed_label:
                    out["network_link_speed"] = speed_label
                    if duplex:
                        out["network_duplex"] = duplex
                else:
                    out["network_link_speed"] = "Auto-negotiated"
                    out["network_duplex"] = "auto"
                if best.get("ip"):
                    out["network_ip"] = best.get("ip")
                out["network_ok"] = True
                out["network_iface_id"] = best.get("id") or "1"
        except ET.ParseError as exc:
            logger.debug("network interfaces parse failed: %s", exc)

    # HTTP answered → never leave interface as down
    if code == 200:
        out.setdefault("network_interface_status", "up")
        out["network_ok"] = True
        if out.get("network_interface_status") == "down":
            out["network_interface_status"] = "up"

    iface_id = str(out.get("network_iface_id") or "1")

    # Dedicated link endpoint (some firmwares expose speed only here)
    if not out.get("network_link_speed"):
        for path in (
            f"/ISAPI/System/Network/interfaces/{iface_id}/link",
            f"/ISAPI/System/Network/interfaces/{iface_id}",
        ):
            sc, sb = _http_get(
                ip, path, username=username, password=password, port=http_port, timeout=8
            )
            if sc != 200 or not sb:
                continue
            try:
                root = ET.fromstring(sb)
                speed = _find_text(root, "speed", "linkSpeed", "Speed")
                duplex = _find_text(root, "duplex", "Duplex")
                link_status = _find_text(
                    root, "linkStatus", "connectionStatus", "operStatus"
                )
                label = _format_link_speed(speed)
                if label:
                    out["network_link_speed"] = label
                    if duplex:
                        out["network_duplex"] = duplex
                elif not out.get("network_link_speed"):
                    out["network_link_speed"] = "Auto-negotiated"
                    out["network_duplex"] = "auto"
                oper = _normalize_link_oper_status(link_status)
                if oper == "up":
                    out["network_interface_status"] = "up"
                if label or duplex:
                    out["network_ok"] = True
                    break
            except ET.ParseError:
                continue

    # Traffic counters when available
    for path in (
        f"/ISAPI/System/Network/interfaces/{iface_id}/statistics",
        f"/ISAPI/System/Network/interfaces/{iface_id}/link/statistics",
        "/ISAPI/System/Network/interfaces/statistics",
    ):
        sc, sb = _http_get(
            ip, path, username=username, password=password, port=http_port, timeout=8
        )
        if sc != 200 or not sb:
            continue
        try:
            root = ET.fromstring(sb)
            rx = _find_text(
                root,
                "recvBytes",
                "rxBytes",
                "bytesReceived",
                "inOctets",
                "ifInOctets",
            )
            tx = _find_text(
                root,
                "sendBytes",
                "txBytes",
                "bytesSent",
                "outOctets",
                "ifOutOctets",
            )
            errs = _find_text(
                root,
                "errorPackets",
                "recvErrorPackets",
                "sendErrorPackets",
                "ifInErrors",
            )
            if rx:
                out["network_rx"] = _format_bytes(rx) or rx
            if tx:
                out["network_tx"] = _format_bytes(tx) or tx
            if errs:
                out["network_errors"] = errs
            if rx or tx:
                break
        except ET.ParseError:
            continue

    return out


def fetch_dahua_network(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    code, body = _http_get(
        ip,
        "/cgi-bin/configManager.cgi?action=getConfig&name=Network",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    if code == 200 and body:
        parsed = _parse_kv(body)
        # eth0.Speed / eth0.LinkMode / eth0.PhysicalAddress
        speed = (
            parsed.get("Network.eth0.Speed")
            or parsed.get("eth0.Speed")
            or parsed.get("Network.eth0.DefaultSpeed")
            or ""
        )
        # Sometimes Speed=0 means auto; DefaultSpeed or LinkMode holds real value
        label = _format_link_speed(speed)
        if not label:
            for k, v in parsed.items():
                if k.lower().endswith(".speed") or k.lower().endswith("linkspeed"):
                    label = _format_link_speed(v)
                    if label:
                        break
        if label:
            out["network_link_speed"] = label
        link = (
            parsed.get("Network.eth0.LinkMode")
            or parsed.get("eth0.LinkMode")
            or parsed.get("Network.eth0.EnableDhcp")
            or ""
        )
        if "dhcp" in str(parsed.get("Network.eth0.DhcpEnable", "")).lower():
            out["network_addressing"] = "dhcp"
        out["network_interface_status"] = "up" if label or link else "up"
        out["network_ok"] = True

    # NetApp work state
    code, body = _http_get(
        ip,
        "/cgi-bin/netApp.cgi?action=getInterfacesInfo",
        username=username,
        password=password,
        port=http_port,
        timeout=8,
    )
    if code == 200 and body:
        parsed = _parse_kv(body)
        for k, v in parsed.items():
            kl = k.lower()
            if "speed" in kl:
                label = _format_link_speed(v)
                if label:
                    out["network_link_speed"] = label
            if "link" in kl and "status" in kl:
                out["network_interface_status"] = v or out.get("network_interface_status")
            if "rx" in kl and ("byte" in kl or "octet" in kl):
                out["network_rx"] = _format_bytes(v) or v
            if "tx" in kl and ("byte" in kl or "octet" in kl):
                out["network_tx"] = _format_bytes(v) or v
        out["network_ok"] = True

    return out


# ─── Hikvision ISAPI ─────────────────────────────────────────────────────────


def fetch_hikvision_channels(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> list[dict[str, Any]]:
    """Pull channel list + online/video-loss/recording from the NVR itself."""
    items: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    # 1) IP camera proxy channels (most NVR deployments)
    code, body = _http_get(
        ip,
        "/ISAPI/ContentMgmt/InputProxy/channels",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            for ch in root.iter():
                if _tag(ch).lower() not in ("inputproxychannel", "channel"):
                    continue
                cid = _find_direct(ch, "id", "channelID") or _find_text(ch, "id")
                if not cid:
                    continue
                name = (
                    _find_direct(ch, "name", "channelName")
                    or _find_text(ch, "name", "channelName")
                    or f"Channel {cid}"
                )
                src_ip = _find_text(ch, "ipAddress", "ipv4Address")
                enabled = _find_text(ch, "enable", "enabled", "online")
                by_id[cid] = {
                    "id": cid,
                    "channel": cid,
                    "name": name,
                    "code": src_ip or "",
                    "status": "online" if (not enabled or _truthy(enabled)) else "offline",
                    "recording": False,
                    "video_loss": False,
                    "source": "nvr_isapi",
                    "last_polled_at": datetime.now(timezone.utc).isoformat(),
                }
        except ET.ParseError as exc:
            logger.debug("InputProxy parse failed: %s", exc)

    # 2) Analog / video input channels (fallback / supplement)
    if not by_id:
        code, body = _http_get(
            ip,
            "/ISAPI/System/Video/inputs/channels",
            username=username,
            password=password,
            port=http_port,
            timeout=10,
        )
        if code == 200 and body:
            try:
                root = ET.fromstring(body)
                for ch in root.iter():
                    if _tag(ch).lower() not in ("videointputchannel", "videoinputchannel", "channel"):
                        continue
                    cid = _find_direct(ch, "id") or _find_text(ch, "id")
                    if not cid:
                        continue
                    name = _find_text(ch, "name", "channelName") or f"Channel {cid}"
                    by_id[cid] = {
                        "id": cid,
                        "channel": cid,
                        "name": name,
                        "code": "",
                        "status": "online",
                        "recording": False,
                        "video_loss": False,
                        "source": "nvr_isapi",
                        "last_polled_at": datetime.now(timezone.utc).isoformat(),
                    }
            except ET.ParseError:
                pass

    # 3) Per-channel / bulk status (online + video loss)
    code, body = _http_get(
        ip,
        "/ISAPI/ContentMgmt/InputProxy/channels/status",
        username=username,
        password=password,
        port=http_port,
        timeout=12,
    )
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            for st in root.iter():
                tag = _tag(st).lower()
                if tag not in (
                    "inputproxychannelstatus",
                    "channelstatus",
                    "status",
                ):
                    # Also match nested status blocks that have an id child
                    if _find_direct(st, "id", "channelID") == "" and tag != "inputproxychannelstatus":
                        continue
                cid = _find_direct(st, "id", "channelID") or _find_text(st, "id", "channelID")
                if not cid:
                    continue
                online_raw = _find_text(st, "online", "chanStatus", "connectionState", "signalStatus")
                video_loss_raw = _find_text(
                    st, "videoLoss", "signalLoss", "chanSrcSignalStatus", "srcSignalStatus"
                )
                online = _truthy(online_raw) if online_raw else True
                # Hikvision often uses online=false for disconnect; signal ok/abnormal
                if online_raw.lower() in ("offline", "disconnect", "disconnected", "0", "false"):
                    online = False
                video_loss = False
                if video_loss_raw:
                    vl = video_loss_raw.lower()
                    video_loss = vl in ("true", "1", "yes", "abnormal", "loss", "videoloss")
                    if vl in ("ok", "normal", "good"):
                        video_loss = False
                entry = by_id.get(cid) or {
                    "id": cid,
                    "channel": cid,
                    "name": f"Channel {cid}",
                    "code": "",
                    "recording": False,
                    "source": "nvr_isapi",
                    "last_polled_at": datetime.now(timezone.utc).isoformat(),
                }
                entry["video_loss"] = video_loss
                entry["status"] = _channel_state_from_flags(online=online, video_loss=video_loss)
                entry["online_raw"] = online_raw
                by_id[cid] = entry
        except ET.ParseError as exc:
            logger.debug("channel status parse failed: %s", exc)
    else:
        # Probe each channel status individually (slower, limited)
        for cid in list(by_id.keys())[:64]:
            sc, sb = _http_get(
                ip,
                f"/ISAPI/ContentMgmt/InputProxy/channels/{cid}/status",
                username=username,
                password=password,
                port=http_port,
                timeout=4,
            )
            if sc != 200 or not sb:
                continue
            try:
                root = ET.fromstring(sb)
                online_raw = _find_text(root, "online", "chanStatus")
                video_loss_raw = _find_text(root, "videoLoss", "srcSignalStatus")
                online = _truthy(online_raw) if online_raw else by_id[cid]["status"] == "online"
                if online_raw.lower() in ("offline", "disconnect", "disconnected", "0", "false"):
                    online = False
                video_loss = video_loss_raw.lower() in (
                    "true",
                    "1",
                    "abnormal",
                    "loss",
                    "videoloss",
                )
                by_id[cid]["status"] = _channel_state_from_flags(
                    online=online, video_loss=video_loss
                )
                by_id[cid]["video_loss"] = video_loss
            except ET.ParseError:
                continue

    # 4) Recording tracks → mark which channels are recording
    code, body = _http_get(
        ip,
        "/ISAPI/ContentMgmt/record/tracks",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    recording_ids: set[str] = set()
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            for tr in root.iter():
                if _tag(tr).lower() not in ("track", "recordingtrack", "tracklist"):
                    if _find_direct(tr, "id", "Channel", "channel") == "" and _tag(tr).lower() != "track":
                        continue
                tid = _find_direct(tr, "id", "Channel", "channel", "channelID") or _find_text(
                    tr, "id", "Channel", "channelID"
                )
                enabled = _find_text(tr, "Enable", "enabled", "recording", "DefaultRecordingMode")
                desc = _find_text(tr, "description", "TrackDescription", "Type")
                # Track IDs often like 101, 201 for channel 1 main/sub
                if tid:
                    # Map 101 → channel 1 style and also keep full id
                    recording_ids.add(tid)
                    if len(tid) >= 3 and tid.isdigit():
                        recording_ids.add(str(int(tid) // 100))
                        recording_ids.add(tid[: len(tid) - 2] if len(tid) > 2 else tid)
                if enabled and not _truthy(enabled) and "disable" in enabled.lower():
                    continue
                if desc and "record" in desc.lower():
                    if tid:
                        recording_ids.add(tid)
        except ET.ParseError:
            pass

    for cid, entry in by_id.items():
        rec = cid in recording_ids
        # Also match track id patterns: channel 1 ↔ 101
        if not rec and cid.isdigit():
            rec = f"{cid}01" in recording_ids or any(
                rid.startswith(cid) for rid in recording_ids if rid.isdigit()
            )
        entry["recording"] = bool(rec)
        items.append(entry)

    # Sort by numeric channel id when possible
    def _sort_key(it: dict[str, Any]):
        c = str(it.get("channel") or "")
        return (0, int(c)) if c.isdigit() else (1, c)

    items.sort(key=_sort_key)
    return items


def fetch_hikvision_logs(
    ip: str,
    *,
    username: str,
    password: str,
    http_port: int = 80,
    page_size: int = 100,
    hours: int = 48,
    max_total: int = 5000,
) -> list[dict[str, Any]]:
    """
    Pull ALL log types from the NVR via ISAPI logSearch with pagination.

    Maps to NVR UI columns:
      Time | Major Type | Subtype | Channel No. | Local/Remote User | Remote Host IP
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(1, hours))
    start_s = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Hikvision major-type codes commonly used in log search
    major_filters: list[str | None] = [
        None,  # unfiltered = all types
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
    ]

    paths = (
        "/ISAPI/ContentMgmt/logSearch",
        "/ISAPI/System/Logs/search",
    )

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _ingest(rows: list[dict[str, Any]]) -> int:
        added = 0
        for row in rows:
            fp = row.get("fingerprint") or _log_fingerprint(row)
            if fp in seen:
                continue
            seen.add(fp)
            row["fingerprint"] = fp
            collected.append(row)
            added += 1
            if len(collected) >= max_total:
                break
        return added

    working_path: str | None = None
    for path in paths:
        # Probe with one unfiltered page
        probe_xml = _hik_log_search_xml(
            start_s, end_s, position=0, max_results=page_size, major_type=None
        )
        code, body = _http_post(
            ip,
            path,
            probe_xml,
            username=username,
            password=password,
            port=http_port,
            timeout=20,
        )
        if code in (200, 201) and body and ("match" in body.lower() or "log" in body.lower()):
            working_path = path
            _ingest(_parse_hikvision_log_xml(body))
            break

    if not working_path:
        # Fallback GET
        code, body = _http_get(
            ip,
            f"/ISAPI/System/Logs?limit={min(page_size, 200)}",
            username=username,
            password=password,
            port=http_port,
            timeout=15,
        )
        if code == 200 and body:
            _ingest(_parse_hikvision_log_xml(body))
        return collected[:max_total]

    # Paginate across major-type filters (ensures Alarm + Information + Operation etc.)
    for major in major_filters:
        if len(collected) >= max_total:
            break
        position = 0
        empty_streak = 0
        for _ in range(0, max_total // max(1, page_size) + 5):
            if len(collected) >= max_total:
                break
            xml_body = _hik_log_search_xml(
                start_s,
                end_s,
                position=position,
                max_results=page_size,
                major_type=major,
            )
            code, body = _http_post(
                ip,
                working_path,
                xml_body,
                username=username,
                password=password,
                port=http_port,
                timeout=25,
            )
            if code not in (200, 201) or not body:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                position += page_size
                continue

            page_rows = _parse_hikvision_log_xml(body)
            status_str = ""
            num_matches = len(page_rows)
            try:
                root = ET.fromstring(body)
                status_str = (_find_text(root, "responseStatusStrg", "statusString") or "").upper()
                raw_n = _find_text(root, "numOfMatches", "totalMatches")
                if raw_n.isdigit():
                    num_matches = int(raw_n)
            except ET.ParseError:
                pass

            added = _ingest(page_rows)
            if "NO MATCHES" in status_str or (num_matches == 0 and not page_rows):
                break
            if not page_rows or added == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0

            # Advance position
            step = len(page_rows) if page_rows else page_size
            if step <= 0:
                break
            position += step
            # MORE means more pages; OK/DONE or short page ends this filter
            if "MORE" in status_str:
                continue
            if len(page_rows) < page_size or status_str in ("OK", "DONE", "TRUE"):
                break

    # Newest first
    collected.sort(key=lambda r: r.get("time") or "", reverse=True)
    return collected[:max_total]


def _hik_log_search_xml(
    start_s: str,
    end_s: str,
    *,
    position: int,
    max_results: int,
    major_type: str | None,
) -> str:
    # Many Hikvision firmwares (incl. DS-77xx V5.04) require metaId + braced searchID
    search_id = "{" + str(uuid.uuid4()) + "}"
    major_block = ""
    if major_type is not None:
        major_block = (
            "\n  <majorTypeList>\n"
            f"    <majorType>{major_type}</majorType>\n"
            "  </majorTypeList>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<CMSearchDescription>"
        f"<searchID>{search_id}</searchID>"
        "<metaId>log.std-cgi.com</metaId>"
        f"<searchResultPosition>{int(position)}</searchResultPosition>"
        f"<maxResults>{int(max_results)}</maxResults>"
        "<timeSpanList>"
        "<timeSpan>"
        f"<startTime>{start_s}</startTime>"
        f"<endTime>{end_s}</endTime>"
        "</timeSpan>"
        "</timeSpanList>"
        f"{major_block}"
        "</CMSearchDescription>"
    )


def _parse_hik_log_meta_id(meta_id: str) -> tuple[str, str, str]:
    """
    Parse metaId like:
      log.hikvision.com/Alarm/motionStart/16
      log.std-cgi.com/Operation/login
    → (major_type, subtype, channel_no)
    """
    parts = [p for p in (meta_id or "").strip().split("/") if p]
    # Drop host-like first segment
    if parts and ("." in parts[0] or parts[0].lower().startswith("log")):
        parts = parts[1:]
    major = parts[0] if parts else ""
    subtype = parts[1] if len(parts) > 1 else ""
    channel = ""
    if len(parts) > 2 and parts[-1].isdigit():
        channel = parts[-1]
        if len(parts) > 2:
            subtype = "/".join(parts[1:-1]) if len(parts) > 2 else subtype
    major_map = {
        "alarm": "Trigger Alarm",
        "exception": "Exception",
        "operation": "Operation",
        "information": "Information",
        "info": "Information",
        "smart": "Smart",
        "event": "Event",
        "industry": "Industry",
    }
    major_label = major_map.get(major.lower(), major or "—")
    return major_label, subtype or "—", channel


_HIK_MAJOR_TYPE_MAP = {
    "0": "None",
    "1": "Trigger Alarm",
    "2": "Exception",
    "3": "Operation",
    "4": "Information",
    "5": "Smart",
    "6": "Event",
    "7": "Industry",
    # text passthrough keys
    "alarm": "Trigger Alarm",
    "trigger alarm": "Trigger Alarm",
    "information": "Information",
    "exception": "Exception",
    "operation": "Operation",
}


def _map_major_type(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "—"
    key = s.lower()
    if key in _HIK_MAJOR_TYPE_MAP:
        return _HIK_MAJOR_TYPE_MAP[key]
    if s.isdigit() and s in _HIK_MAJOR_TYPE_MAP:
        return _HIK_MAJOR_TYPE_MAP[s]
    return s


def _parse_log_time(raw: str) -> datetime | None:
    if not raw or raw == "—":
        return None
    text = raw.strip().replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(text.replace("+00:00", ""), fmt) if "%z" not in fmt else datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        # fromisoformat handles many cases
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _log_fingerprint(row: dict[str, Any]) -> str:
    import hashlib

    parts = "|".join(
        [
            str(row.get("time") or ""),
            str(row.get("major_type") or ""),
            str(row.get("subtype") or row.get("minor_type") or ""),
            str(row.get("channel_no") or row.get("channel") or ""),
            str(row.get("local_remote_user") or row.get("user") or ""),
            str(row.get("remote_host_ip") or ""),
            str(row.get("description") or ""),
        ]
    )
    return hashlib.sha1(parts.encode("utf-8", errors="ignore")).hexdigest()


def _parse_hikvision_log_xml(body: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return rows

    def _dash(v: str) -> str:
        v = (v or "").strip()
        return v if v and v.lower() not in ("0", "none", "null", "") else "--"

    # Prefer logDescriptor nodes (Hikvision DS-77xx / PSIA-style results)
    descriptors = [el for el in root.iter() if _tag(el).lower() == "logdescriptor"]
    targets = descriptors or [
        el
        for el in root.iter()
        if _tag(el).lower()
        in ("searchmatchitem", "matchelement", "logitem", "logentry", "item")
    ]

    for item in targets:
        meta_id = (
            _find_direct(item, "metaId", "MetaId")
            or _find_text(item, "metaId", "MetaId")
            or ""
        )
        ts = (
            _find_direct(
                item,
                "StartDateTime",
                "startDateTime",
                "time",
                "logTime",
                "dateTime",
                "startTime",
            )
            or _find_text(
                item,
                "StartDateTime",
                "startDateTime",
                "time",
                "logTime",
                "dateTime",
                "startTime",
            )
            or "—"
        )
        major_raw = (
            _find_direct(item, "majorType", "MajorType")
            or _find_text(item, "majorType", "MajorType", "major")
            or ""
        )
        subtype = (
            _find_direct(item, "minorType", "MinorType", "subType")
            or _find_text(item, "minorType", "MinorType", "subType", "eventType", "name")
            or ""
        )
        channel = (
            _find_direct(item, "channelID", "channelNo", "channel", "dynChannelID", "localID")
            or _find_text(item, "channelID", "channelNo", "channel", "dynChannelID", "localID")
            or ""
        )
        if meta_id:
            m_major, m_sub, m_ch = _parse_hik_log_meta_id(meta_id)
            if not major_raw:
                major_raw = m_major
            if not subtype or subtype == "—":
                subtype = m_sub
            if not channel or channel in ("0", "D0"):
                channel = m_ch or channel
        # localID often like D16 → channel 16
        if channel.upper().startswith("D") and channel[1:].isdigit():
            channel = channel[1:]

        user = (
            _find_direct(item, "userName", "localUserName", "user", "localOrRemoteUser", "panelUser")
            or _find_text(item, "userName", "localUserName", "user", "localOrRemoteUser", "panelUser")
            or ""
        )
        remote_ip = (
            _find_direct(item, "remoteHostIP", "ipAddress", "remoteIP", "hostIP")
            or _find_text(item, "remoteHostIP", "ipAddress", "remoteIP", "hostIP")
            or ""
        )
        desc = (
            _find_direct(item, "description", "logDescription", "info", "detail")
            or _find_text(item, "description", "logDescription", "info", "detail")
            or subtype
            or meta_id
            or "—"
        )
        if not major_raw and not subtype and (not ts or ts == "—") and not meta_id:
            continue

        row = {
            "time": ts,
            "major_type": _map_major_type(major_raw) if major_raw and major_raw[0].isdigit() else (major_raw or "—"),
            "subtype": subtype or "—",
            "minor_type": subtype or "—",
            "channel_no": _dash(channel),
            "channel": _dash(channel),
            "local_remote_user": _dash(user),
            "user": _dash(user),
            "remote_host_ip": _dash(remote_ip),
            "description": desc,
            "meta_id": meta_id,
            "source": "nvr_isapi",
        }
        row["fingerprint"] = _log_fingerprint(row)
        rows.append(row)
    return rows


def persist_nvr_logs(device, logs: list[dict[str, Any]]) -> int:
    """Upsert NVR log rows into InfraNvrLog. Returns number newly created."""
    from .models import InfraNvrLog

    created = 0
    for row in logs or []:
        fp = row.get("fingerprint") or _log_fingerprint(row)
        dt = _parse_log_time(str(row.get("time") or ""))
        if dt is None:
            dt = datetime.now(timezone.utc)
        obj, was_created = InfraNvrLog.objects.get_or_create(
            device=device,
            fingerprint=fp,
            defaults={
                "log_time": dt,
                "major_type": (row.get("major_type") or "")[:128],
                "subtype": (row.get("subtype") or row.get("minor_type") or "")[:256],
                "channel_no": (row.get("channel_no") or row.get("channel") or "")[:32],
                "local_remote_user": (
                    row.get("local_remote_user") or row.get("user") or ""
                )[:128],
                "remote_host_ip": (row.get("remote_host_ip") or "")[:64],
                "description": row.get("description") or "",
                "raw": row,
            },
        )
        if was_created:
            created += 1
        else:
            # Keep raw updated
            obj.raw = row
            obj.save(update_fields=["raw"])
    return created


def load_stored_nvr_logs(device, *, limit: int = 5000) -> list[dict[str, Any]]:
    from .models import InfraNvrLog

    qs = InfraNvrLog.objects.filter(device=device).order_by("-log_time", "-id")[:limit]
    out = []
    for i, row in enumerate(qs, start=1):
        out.append(
            {
                "no": i,
                "time": row.log_time.strftime("%Y-%m-%d %H:%M:%S") if row.log_time else "—",
                "major_type": row.major_type or "—",
                "subtype": row.subtype or "—",
                "minor_type": row.subtype or "—",
                "channel_no": row.channel_no or "--",
                "channel": row.channel_no or "--",
                "local_remote_user": row.local_remote_user or "--",
                "user": row.local_remote_user or "--",
                "remote_host_ip": row.remote_host_ip or "--",
                "description": row.description or row.subtype or "—",
                "source": "nvr_db",
                "fingerprint": row.fingerprint,
            }
        )
    # Re-number so No. 1 is oldest or newest? NVR UI shows ascending No. with time order.
    # User sample: No. 8,9,10... with chronological time — keep newest-first display
    # but number 1..n in current list order (newest first).
    for i, row in enumerate(out, start=1):
        row["no"] = i
    return out


def _format_uptime(seconds: Any, raw: Any = None) -> str:
    """Format device uptime; raw numeric strings are treated as seconds."""
    secs = None
    try:
        if seconds is not None:
            secs = int(float(seconds))
    except (TypeError, ValueError):
        secs = None
    if secs is None and raw is not None:
        text = str(raw).strip()
        # Pure number → seconds
        try:
            if text.replace(".", "", 1).isdigit():
                secs = int(float(text))
        except ValueError:
            pass
        if secs is None and text:
            # Already human-readable
            return text
    if secs is None or secs < 0:
        return ""
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _clamp_percent(val: float | None) -> float | None:
    if val is None:
        return None
    if val < 0:
        return None
    # Values like 2288 are MB totals wrongly used as %
    if val > 100:
        return None
    return round(float(val), 1)


def parse_hikvision_device_status_xml(body: str) -> dict[str, Any]:
    """
    Parse /ISAPI/System/status XML into cpu/ram/temp/uptime.

    Hikvision typically nests:
      <CPUList><CPU><cpuUtilization>12</cpuUtilization></CPU></CPUList>
      <MemoryList><Memory>
        <memoryUsage>45</memoryUsage>  OR available/total in KB/MB
      </Memory></MemoryList>
      <deviceUpTime>404371</deviceUpTime>
    """
    out: dict[str, Any] = {}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out

    # —— CPU: average cpuUtilization nodes (do not double-count parent+child) ——
    cpu_vals: list[float] = []
    for el in root.iter():
        t = _tag(el).lower()
        if t in ("cpuutilization", "cpuusage") and el.text:
            v = _safe_float(el.text)
            if v is not None and 0 <= v <= 100:
                cpu_vals.append(v)
    if cpu_vals:
        out["cpu_percent"] = round(sum(cpu_vals) / len(cpu_vals), 1)
    else:
        out["cpu_percent"] = _clamp_percent(
            _safe_float(_find_text(root, "cpuUtilization", "CPUUtilization", "cpuUsage"))
        )

    # —— Memory ——
    # Hikvision often reports memoryUsage as *used MB* (e.g. 2286) plus
    # memoryAvailable as free MB — not a percentage. Older firmwares may
    # put a 0–100 percent in memoryUsage instead.
    mem_pct = None
    mem_total = None
    mem_avail = None
    mem_used = None
    for el in root.iter():
        t = _tag(el).lower()
        if t == "memory":
            usage = _safe_float(
                _find_direct(el, "memoryUsage", "memoryUtilization", "usage")
            )
            total = _safe_float(
                _find_direct(el, "memoryTotal", "total", "memorySize", "size")
            )
            avail = _safe_float(
                _find_direct(el, "memoryAvailable", "available", "freeMemory", "free")
            )
            used = _safe_float(_find_direct(el, "memoryUsed", "used"))
            if usage is not None and 0 <= usage <= 100:
                mem_pct = usage
            elif usage is not None and usage > 100:
                mem_used = usage
            if total is not None:
                mem_total = total
            if avail is not None:
                mem_avail = avail
            if used is not None:
                mem_used = used
        elif t in ("memoryusage", "memoryutilization"):
            v = _safe_float(el.text)
            if v is not None and 0 <= v <= 100:
                mem_pct = v
            elif v is not None and v > 100:
                mem_used = v
        elif t in ("memorytotal", "totalmemory"):
            mem_total = _safe_float(el.text) or mem_total
        elif t in ("memoryavailable", "freememory", "availablememory"):
            mem_avail = _safe_float(el.text) or mem_avail
        elif t in ("memoryused", "usedmemory"):
            mem_used = _safe_float(el.text) or mem_used

    if mem_pct is None:
        if mem_total and mem_total > 0:
            if mem_used is not None:
                mem_pct = (mem_used / mem_total) * 100
            elif mem_avail is not None:
                mem_pct = ((mem_total - mem_avail) / mem_total) * 100
        elif mem_used is not None and mem_avail is not None and (mem_used + mem_avail) > 0:
            # used MB + free MB → derive total and percent
            mem_total = mem_used + mem_avail
            mem_pct = (mem_used / mem_total) * 100

    out["memory_percent"] = _clamp_percent(mem_pct)
    if mem_total:
        out["memory_total"] = mem_total
    if mem_avail is not None:
        out["memory_available"] = mem_avail
    if mem_used is not None:
        out["memory_used"] = mem_used

    # —— Uptime (seconds) ——
    uptime = _find_text(root, "deviceUpTime", "upTime", "Uptime", "runTime")
    if uptime:
        out["uptime_raw"] = uptime
        secs = _safe_float(uptime)
        if secs is not None:
            out["uptime_seconds"] = secs
        out["uptime"] = _format_uptime(secs, uptime)

    # —— Temperature ——
    temp_vals: list[float] = []
    for el in root.iter():
        t = _tag(el).lower()
        if t in (
            "temperature",
            "devicetemperature",
            "cputemperature",
            "boardtemperature",
            "hightemperature",
            "temp",
        ):
            v = _safe_float(el.text)
            # Reasonable electronics range °C (or sometimes 10x)
            if v is None:
                continue
            if 0 <= v <= 120:
                temp_vals.append(v)
            elif 200 <= v <= 1200:
                # decidegrees
                temp_vals.append(v / 10.0)
    if temp_vals:
        out["temperature_c"] = round(sum(temp_vals) / len(temp_vals), 1)

    # Do NOT search bare "status" — it matches unrelated nested nodes (often "unknown")
    state = (
        _find_text(root, "deviceStatus", "workStatus", "deviceState")
        or _find_direct(root, "deviceStatus", "workStatus", "deviceState")
    )
    if state and state.lower() not in ("static", "dhcp", "unknown", ""):
        out["system_state"] = state
    else:
        out.setdefault("system_state", "normal")

    out["system_status_ok"] = True
    return out


def fetch_hikvision_system_health(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> dict[str, Any]:
    """CPU / RAM / temperature / uptime from NVR status (+ fallback endpoints)."""
    out: dict[str, Any] = {}
    code, body = _http_get(
        ip,
        "/ISAPI/System/status",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    if code == 200 and body:
        out.update(parse_hikvision_device_status_xml(body))

    # Extra hardware / thermal endpoints used by some firmwares
    if out.get("temperature_c") is None or out.get("cpu_percent") is None:
        for path in (
            "/ISAPI/System/HardwareStatus",
            "/ISAPI/System/hardwareStatus",
            "/ISAPI/System/deviceStatus",
            "/ISAPI/System/WorkStatus",
        ):
            sc, sb = _http_get(
                ip, path, username=username, password=password, port=http_port, timeout=8
            )
            if sc != 200 or not sb:
                continue
            parsed = parse_hikvision_device_status_xml(sb)
            if out.get("cpu_percent") is None and parsed.get("cpu_percent") is not None:
                out["cpu_percent"] = parsed["cpu_percent"]
            if out.get("memory_percent") is None and parsed.get("memory_percent") is not None:
                out["memory_percent"] = parsed["memory_percent"]
            if out.get("temperature_c") is None and parsed.get("temperature_c") is not None:
                out["temperature_c"] = parsed["temperature_c"]
            if out.get("uptime_seconds") is None and parsed.get("uptime_seconds") is not None:
                out["uptime_seconds"] = parsed["uptime_seconds"]
                out["uptime"] = parsed.get("uptime") or _format_uptime(
                    parsed.get("uptime_seconds")
                )
            if parsed.get("system_state"):
                out.setdefault("system_state", parsed["system_state"])

    # Dahua-style CPU/mem if still missing (some rebranded units)
    if out.get("cpu_percent") is None:
        sc, sb = _http_get(
            ip,
            "/cgi-bin/magicBox.cgi?action=getCPUUsage",
            username=username,
            password=password,
            port=http_port,
            timeout=6,
        )
        if sc == 200 and sb:
            parsed = _parse_kv(sb)
            out["cpu_percent"] = _clamp_percent(
                _safe_float(parsed.get("usage") or parsed.get("CPUUsage"))
            )

    if out.get("memory_percent") is None:
        sc, sb = _http_get(
            ip,
            "/cgi-bin/magicBox.cgi?action=getMemoryInfo",
            username=username,
            password=password,
            port=http_port,
            timeout=6,
        )
        if sc == 200 and sb:
            parsed = _parse_kv(sb)
            total = _safe_float(parsed.get("total"))
            free = _safe_float(parsed.get("free"))
            if total and free is not None and total > 0:
                out["memory_percent"] = _clamp_percent(((total - free) / total) * 100)

    if out.get("uptime") is None and out.get("uptime_seconds") is not None:
        out["uptime"] = _format_uptime(out["uptime_seconds"], out.get("uptime_raw"))

    return out


def _parse_hdd_elements(root: Element) -> list[dict[str, Any]]:
    """Extract per-disk capacity/free/status from Storage or Storage/hdd XML.

    Hikvision documents capacity and freeSpace in MB. On many NVRs freeSpace stays
    0 while status=ok (volume / circular recording). Prefer Storage/quota for real
    free space — applied later in fetch_hikvision_storage.
    """
    raw_hdds: list[dict[str, Any]] = []
    hdd_idx = 0
    for hdd in root.iter():
        if _tag(hdd).lower() != "hdd":
            continue
        hdd_idx += 1
        status = (
            _find_direct(hdd, "status", "hddStatus")
            or _find_direct(hdd, "hddStatus")
            or "unknown"
        )
        cap_raw = _find_direct(
            hdd, "capacity", "hddCapacity", "capacityMB", "volume"
        )
        free_raw = _find_direct(
            hdd,
            "freeSpace",
            "hddFreeSpace",
            "freeSpaceMB",
            "freeSize",
            "freesize",
            "free",
        )
        if not cap_raw:
            cap_raw = _find_text(hdd, "capacity", "hddCapacity", "capacityMB")
        if not free_raw:
            free_raw = _find_text(
                hdd, "freeSpace", "hddFreeSpace", "freeSpaceMB", "freeSize", "freesize"
            )
        cap = _safe_float(cap_raw)
        free = _safe_float(free_raw) if free_raw not in ("", None) else None
        disk_id = (
            _find_direct(hdd, "id", "hddId", "hddName", "name")
            or str(hdd_idx)
        )
        disk_type = _find_direct(hdd, "hddType", "type") or ""
        disk_model = _find_direct(hdd, "hddModel", "model") or ""
        disk_serial = _find_direct(hdd, "hddSerialNumber", "serialNumber") or ""
        prop = (_find_direct(hdd, "property") or "").strip().upper()
        # NVR UI Attribute: RW → R/W
        attribute = {"RW": "R/W", "RO": "R/O", "REDUND": "Redundant"}.get(prop, prop or "")
        # NVR UI Type: SATA local drives shown as Local
        type_label = "Local" if disk_type.upper() in ("SATA", "SAS", "LOCAL", "") else disk_type
        entry: dict[str, Any] = {
            "id": disk_id,
            "disk_number": disk_id,
            "status": status,
            "disk_type": type_label or disk_type,
            "disk_model": disk_model,
            "disk_serial": disk_serial,
            "attribute": attribute,
            "property": prop,
        }
        if cap is not None:
            entry["capacity_mb"] = cap
        if free is not None:
            entry["free_mb"] = free
            if cap is not None:
                entry["used_mb"] = max(0.0, cap - free)
        raw_hdds.append(entry)
    return raw_hdds


def _fetch_hikvision_volume_quota(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> dict[str, float]:
    """
    /ISAPI/ContentMgmt/Storage/quota — real volume free space.

    On DS-77xx / similar, per-HDD freeSpace is often stuck at 0 while
    freeVideoQuota reports the true remaining recording capacity (MB).
    """
    code, body = _http_get(
        ip,
        "/ISAPI/ContentMgmt/Storage/quota",
        username=username,
        password=password,
        port=http_port,
        timeout=12,
    )
    if code != 200 or not body:
        return {}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {}

    best_total = None
    best_free = None
    for node in root.iter():
        if _tag(node).lower() != "diskquota":
            continue
        total = _safe_float(
            _find_direct(node, "totalDiskVolume", "totalCapacity", "capacity")
        )
        free = _safe_float(
            _find_direct(
                node,
                "freeVideoQuota",
                "freePictureQuota",
                "freeSpace",
                "freeCapacity",
            )
        )
        if total is None or free is None or total <= 0:
            continue
        # Prefer the largest consistent volume reading
        if best_total is None or total > best_total:
            best_total = total
            best_free = free
    if best_total is None or best_free is None:
        return {}
    free = max(0.0, min(float(best_free), float(best_total)))
    return {
        "volume_total_mb": float(best_total),
        "volume_free_mb": free,
        "volume_used_mb": max(0.0, float(best_total) - free),
    }


def _merge_hdd_rows(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge Storage + Storage/hdd rows by disk id; prefer rows with free_mb."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _key(row: dict[str, Any]) -> str:
        return str(row.get("id") or row.get("disk_number") or "")

    for row in primary + secondary:
        k = _key(row)
        if not k:
            continue
        if k not in by_id:
            by_id[k] = dict(row)
            order.append(k)
            continue
        cur = by_id[k]
        for field in (
            "status",
            "disk_type",
            "disk_model",
            "disk_serial",
            "attribute",
            "property",
            "capacity_mb",
            "free_mb",
            "used_mb",
        ):
            if cur.get(field) in (None, "", "unknown") and row.get(field) not in (
                None,
                "",
            ):
                cur[field] = row[field]
        # Prefer explicit free_mb from either side
        if cur.get("free_mb") is None and row.get("free_mb") is not None:
            cur["free_mb"] = row["free_mb"]
            if cur.get("capacity_mb") is not None:
                cur["used_mb"] = max(0.0, float(cur["capacity_mb"]) - float(row["free_mb"]))
        if (not cur.get("status") or cur.get("status") == "unknown") and row.get("status"):
            cur["status"] = row["status"]
    return [by_id[k] for k in order]


def fetch_hikvision_storage(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> dict[str, Any]:
    """Pull HDD list + real volume free space from Storage, Storage/hdd, quota."""
    out: dict[str, Any] = {}
    rows_a: list[dict[str, Any]] = []
    rows_b: list[dict[str, Any]] = []

    for path, bucket in (
        ("/ISAPI/ContentMgmt/Storage", "a"),
        ("/ISAPI/ContentMgmt/Storage/hdd", "b"),
    ):
        code, body = _http_get(
            ip, path, username=username, password=password, port=http_port, timeout=12
        )
        if code != 200 or not body:
            continue
        try:
            root = ET.fromstring(body)
            parsed = _parse_hdd_elements(root)
            if bucket == "a":
                rows_a = parsed
            else:
                rows_b = parsed
        except ET.ParseError as exc:
            logger.debug("storage parse failed %s: %s", path, exc)

    # Prefer Storage/hdd (often includes model/serial)
    prefer_b = bool(rows_b)
    raw_hdds = (
        _merge_hdd_rows(rows_b, rows_a) if prefer_b else _merge_hdd_rows(rows_a, rows_b)
    )

    # Enrich model/serial from per-disk endpoints when list omitted them
    for row in raw_hdds:
        if row.get("disk_model") and row.get("disk_serial"):
            continue
        disk_id = str(row.get("id") or row.get("disk_number") or "").strip()
        if not disk_id:
            continue
        sc, sb = _http_get(
            ip,
            f"/ISAPI/ContentMgmt/Storage/hdd/{disk_id}",
            username=username,
            password=password,
            port=http_port,
            timeout=8,
        )
        if sc != 200 or not sb:
            continue
        try:
            one = _parse_hdd_elements(ET.fromstring(sb))
            if one:
                if not row.get("disk_model") and one[0].get("disk_model"):
                    row["disk_model"] = one[0]["disk_model"]
                if not row.get("disk_serial") and one[0].get("disk_serial"):
                    row["disk_serial"] = one[0]["disk_serial"]
                if (not row.get("status") or row.get("status") == "unknown") and one[0].get(
                    "status"
                ):
                    row["status"] = one[0]["status"]
        except ET.ParseError:
            continue

    quota = _fetch_hikvision_volume_quota(
        ip, username=username, password=password, http_port=http_port
    )
    capacity_sum = sum(float(r.get("capacity_mb") or 0) for r in raw_hdds)
    volume_free = quota.get("volume_free_mb")
    volume_total = quota.get("volume_total_mb") or capacity_sum

    # Prefer exact per-disk freeSpace from ISAPI (matches NVR Storage table).
    # Only fall back to volume quota when NO disk reports freeSpace at all.
    any_disk_reports_free = any(r.get("free_mb") is not None for r in raw_hdds)
    free_values_missing = bool(raw_hdds) and all(r.get("free_mb") is None for r in raw_hdds)
    if (
        free_values_missing
        and volume_free is not None
        and volume_free > 0
        and capacity_sum > 0
    ):
        for r in raw_hdds:
            cap = float(r.get("capacity_mb") or 0)
            if cap <= 0:
                continue
            share = volume_free * (cap / capacity_sum)
            r["free_mb"] = share
            r["used_mb"] = max(0.0, cap - share)
        out["storage_free_source"] = "quota"
    elif any_disk_reports_free:
        out["storage_free_source"] = "hdd"
    elif volume_free is not None:
        out["storage_free_source"] = "quota"
    else:
        out["storage_free_source"] = "hdd"

    hdds = normalize_hdd_list(raw_hdds)
    if not hdds:
        out["storage_ok"] = False
        return out

    errors = sum(1 for h in hdds if h.get("level") == "critical")
    warns = sum(1 for h in hdds if h.get("level") == "warning")
    fulls = sum(1 for h in hdds if h.get("health_label") == "Full")
    sleeps = sum(1 for h in hdds if h.get("health_label") == "Sleep")
    capacity_total = sum(float(h.get("capacity_mb") or 0) for h in hdds)

    # Aggregate from per-disk values when available (exact NVR Remaining Capacity sum)
    free_known = [h for h in hdds if h.get("free_known")]
    if free_known:
        free_total = sum(float(h.get("free_mb") or 0) for h in free_known)
        used_total = sum(
            float(h.get("used_mb") if h.get("used_mb") is not None else max(0.0, float(h.get("capacity_mb") or 0) - float(h.get("free_mb") or 0)))
            for h in hdds
        )
        out["hdd_capacity_mb"] = capacity_total
        out["hdd_free_mb"] = free_total
        out["hdd_used_mb"] = used_total
    elif volume_free is not None and volume_total:
        out["hdd_capacity_mb"] = capacity_total or float(volume_total)
        out["hdd_free_mb"] = float(volume_free)
        out["hdd_used_mb"] = max(0.0, float(volume_total) - float(volume_free))
    else:
        out["hdd_capacity_mb"] = capacity_total

    out["hdd_list"] = hdds
    out["hdd_count"] = len(hdds)
    if errors:
        out["hdd_status"] = "error"
    elif sleeps and not fulls and warns == sleeps:
        out["hdd_status"] = "sleep"
    elif fulls and fulls == warns:
        out["hdd_status"] = "full"
    elif warns:
        out["hdd_status"] = "warning"
    else:
        out["hdd_status"] = "ok"
    out["hdd_errors"] = errors
    out["storage_ok"] = True
    return out


def probe_hikvision_isapi(
    ip: str,
    *,
    username: str,
    password: str,
    http_port: int = 80,
) -> dict[str, Any]:
    """System/storage/network + channels + logs from Hikvision-compatible NVR."""
    metrics: dict[str, Any] = {"vendor_probe": "hikvision_isapi"}

    code, body = _http_get(
        ip, "/ISAPI/System/deviceInfo", username=username, password=password, port=http_port
    )
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            metrics["device_model"] = _find_text(root, "model", "deviceName")
            metrics["firmware_version"] = _find_text(root, "firmwareVersion", "firmwareVersionInfo")
            metrics["device_name"] = _find_text(root, "deviceName", "deviceID")
            metrics["serial_number"] = _find_text(root, "serialNumber")
            metrics["mac_address"] = _find_text(root, "macAddress")
            metrics["device_info_ok"] = True
        except ET.ParseError:
            metrics["device_info_ok"] = False

    metrics.update(
        fetch_hikvision_system_health(
            ip, username=username, password=password, http_port=http_port
        )
    )

    storage = fetch_hikvision_storage(
        ip, username=username, password=password, http_port=http_port
    )
    metrics.update(storage)

    net = fetch_hikvision_network(
        ip, username=username, password=password, http_port=http_port
    )
    metrics.update(net)

    code, body = _http_get(
        ip,
        "/ISAPI/ContentMgmt/record/tracks",
        username=username,
        password=password,
        port=http_port,
    )
    if code == 200:
        metrics["recording_status"] = "available"
        metrics["recording_ok"] = True
    elif code is not None:
        metrics["recording_status"] = "unknown"
        metrics["recording_ok"] = False

    # Channels + logs from NVR
    try:
        ch_items = fetch_hikvision_channels(
            ip, username=username, password=password, http_port=http_port
        )
        channels = _summarize_channels(ch_items)
        metrics["channels"] = channels
        metrics["channels_source"] = "nvr"
        metrics["channels_online"] = channels["online"]
        metrics["channels_offline"] = channels["offline"]
        metrics["channels_video_loss"] = channels["video_loss"]
        metrics["channels_recording"] = channels["recording"]
        metrics["channels_total"] = channels["total"]
        if channels["total"]:
            metrics["channels_ok"] = True
    except Exception as exc:
        metrics["channels_error"] = str(exc)[:200]

    try:
        logs = fetch_hikvision_logs(
            ip,
            username=username,
            password=password,
            http_port=http_port,
            page_size=100,
            hours=72,
            max_total=5000,
        )
        metrics["nvr_logs"] = logs
        metrics["nvr_logs_count"] = len(logs)
        metrics["nvr_logs_ok"] = True
    except Exception as exc:
        metrics["nvr_logs"] = []
        metrics["nvr_logs_error"] = str(exc)[:200]

    return metrics


# ─── Dahua CGI ───────────────────────────────────────────────────────────────


def fetch_dahua_channels(
    ip: str, *, username: str, password: str, http_port: int = 80
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    # Camera connection state
    code, body = _http_get(
        ip,
        "/cgi-bin/logicDeviceManager.cgi?action=getCameraState&channel=all",
        username=username,
        password=password,
        port=http_port,
        timeout=12,
    )
    states: dict[str, str] = {}
    if code == 200 and body:
        parsed = _parse_kv(body)
        # keys like channels[0].channel=1 / channels[0].connectionState=Connected
        tmp: dict[str, dict[str, str]] = {}
        for k, v in parsed.items():
            if not k.startswith("channels["):
                continue
            try:
                idx = k.split("[", 1)[1].split("]", 1)[0]
                field = k.split(".", 1)[1] if "." in k else "value"
            except IndexError:
                continue
            tmp.setdefault(idx, {})[field] = v
        for idx, fields in tmp.items():
            ch = fields.get("channel") or fields.get("UniqueChannel") or str(int(idx) + 1)
            conn = fields.get("connectionState") or fields.get("state") or ""
            states[ch] = conn

    code, body = _http_get(
        ip,
        "/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle",
        username=username,
        password=password,
        port=http_port,
        timeout=10,
    )
    titles: dict[str, str] = {}
    if code == 200 and body:
        parsed = _parse_kv(body)
        for k, v in parsed.items():
            # ChannelTitle[0].Name=Gate
            if "ChannelTitle[" in k and k.endswith(".Name"):
                try:
                    idx = k.split("[", 1)[1].split("]", 1)[0]
                    titles[str(int(idx) + 1)] = v
                except ValueError:
                    pass

    # Build channel list from states or titles
    ids = sorted(set(states.keys()) | set(titles.keys()), key=lambda x: int(x) if x.isdigit() else x)
    if not ids:
        # Assume 16 channels if device answers system info only
        return items

    for ch in ids:
        conn = (states.get(ch) or "").lower()
        video_loss = "loss" in conn or "abnormal" in conn
        online = conn in ("connected", "connect", "ok", "normal", "online") or (
            conn == "" and ch in titles
        )
        if "disconnect" in conn or conn in ("idle", "empty", "none"):
            online = False
        status = _channel_state_from_flags(online=online, video_loss=video_loss)
        items.append(
            {
                "id": ch,
                "channel": ch,
                "name": titles.get(ch) or f"Channel {ch}",
                "code": "",
                "status": status,
                "recording": False,
                "video_loss": video_loss,
                "source": "nvr_dahua",
                "last_polled_at": datetime.now(timezone.utc).isoformat(),
                "connection_state": states.get(ch, ""),
            }
        )
    return items


def fetch_dahua_logs(
    ip: str,
    *,
    username: str,
    password: str,
    http_port: int = 80,
    max_results: int = 5000,
    hours: int = 72,
) -> list[dict[str, Any]]:
    end = datetime.now()
    start = end - timedelta(hours=max(1, hours))
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")
    code, body = _http_get(
        ip,
        (
            "/cgi-bin/log.cgi?action=startFind"
            f"&condition.StartTime={quote(start_s)}"
            f"&condition.EndTime={quote(end_s)}"
        ),
        username=username,
        password=password,
        port=http_port,
        timeout=15,
    )
    token = ""
    if code == 200 and body:
        parsed = _parse_kv(body)
        token = parsed.get("token") or parsed.get("result") or ""
    logs: list[dict[str, Any]] = []
    if not token:
        return logs

    # Paginate doFind
    remaining = max_results
    while remaining > 0:
        batch = min(100, remaining)
        sc, sb = _http_get(
            ip,
            f"/cgi-bin/log.cgi?action=doFind&token={token}&count={batch}",
            username=username,
            password=password,
            port=http_port,
            timeout=20,
        )
        if sc != 200 or not sb:
            break
        parsed = _parse_kv(sb)
        buckets: dict[str, dict[str, str]] = {}
        for k, v in parsed.items():
            if not k.startswith("items["):
                continue
            try:
                idx = k.split("[", 1)[1].split("]", 1)[0]
                field = k.split(".", 1)[1]
            except IndexError:
                continue
            buckets.setdefault(idx, {})[field] = v
        if not buckets:
            break
        for idx in sorted(buckets.keys(), key=lambda x: int(x) if x.isdigit() else x):
            f = buckets[idx]
            row = {
                "time": f.get("Time") or f.get("time") or "—",
                "major_type": _map_major_type(f.get("Type") or f.get("type") or ""),
                "subtype": f.get("Detail") or f.get("detail") or f.get("Content") or "—",
                "minor_type": f.get("Detail") or f.get("detail") or "—",
                "channel_no": f.get("Channel") or f.get("channel") or "--",
                "channel": f.get("Channel") or f.get("channel") or "--",
                "local_remote_user": f.get("User") or f.get("user") or "--",
                "user": f.get("User") or "--",
                "remote_host_ip": f.get("Address") or f.get("RemoteAddress") or "--",
                "description": f.get("Detail") or f.get("detail") or "—",
                "source": "nvr_dahua",
            }
            row["fingerprint"] = _log_fingerprint(row)
            logs.append(row)
        remaining -= len(buckets)
        if len(buckets) < batch:
            break

    _http_get(
        ip,
        f"/cgi-bin/log.cgi?action=stopFind&token={token}",
        username=username,
        password=password,
        port=http_port,
        timeout=5,
    )
    return logs[:max_results]


def probe_dahua_cgi(
    ip: str,
    *,
    username: str,
    password: str,
    http_port: int = 80,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"vendor_probe": "dahua_cgi"}
    code, body = _http_get(
        ip,
        "/cgi-bin/magicBox.cgi?action=getSystemInfo",
        username=username,
        password=password,
        port=http_port,
    )
    if code == 200 and body:
        parsed = _parse_kv(body)
        metrics["device_model"] = parsed.get("deviceType") or parsed.get("serialNumber", "")
        metrics["serial_number"] = parsed.get("serialNumber", "")
        metrics["firmware_version"] = parsed.get("updateSerial") or parsed.get(
            "hardwareVersion", ""
        )
        metrics["device_info_ok"] = True

    code, body = _http_get(
        ip,
        "/cgi-bin/magicBox.cgi?action=getCPUUsage",
        username=username,
        password=password,
        port=http_port,
    )
    if code == 200 and body:
        parsed = _parse_kv(body)
        metrics["cpu_percent"] = _safe_float(parsed.get("usage") or parsed.get("CPUUsage"))

    code, body = _http_get(
        ip,
        "/cgi-bin/magicBox.cgi?action=getMemoryInfo",
        username=username,
        password=password,
        port=http_port,
    )
    if code == 200 and body:
        parsed = _parse_kv(body)
        total = _safe_float(parsed.get("total"))
        free = _safe_float(parsed.get("free"))
        if total and free is not None and total > 0:
            metrics["memory_percent"] = round(((total - free) / total) * 100, 1)

    try:
        metrics.update(
            fetch_dahua_network(ip, username=username, password=password, http_port=http_port)
        )
    except Exception as exc:
        metrics["network_error"] = str(exc)[:200]

    try:
        ch_items = fetch_dahua_channels(
            ip, username=username, password=password, http_port=http_port
        )
        channels = _summarize_channels(ch_items)
        metrics["channels"] = channels
        metrics["channels_source"] = "nvr"
        metrics["channels_online"] = channels["online"]
        metrics["channels_offline"] = channels["offline"]
        metrics["channels_video_loss"] = channels["video_loss"]
        metrics["channels_recording"] = channels["recording"]
        metrics["channels_total"] = channels["total"]
    except Exception as exc:
        metrics["channels_error"] = str(exc)[:200]

    try:
        logs = fetch_dahua_logs(ip, username=username, password=password, http_port=http_port)
        metrics["nvr_logs"] = logs
        metrics["nvr_logs_count"] = len(logs)
        metrics["nvr_logs_ok"] = True
    except Exception as exc:
        metrics["nvr_logs"] = []
        metrics["nvr_logs_error"] = str(exc)[:200]

    return metrics


# ─── Orchestration ───────────────────────────────────────────────────────────


def enrich_nvr_metrics(device) -> dict[str, Any]:
    """
    Probe the NVR appliance directly for health, camera channels, and logs.
    Does NOT use TekEye Camera Management camera records for channel status.
    """
    from .models import DeviceStatus

    # Drop stale probe fields so a new poll cannot keep wrong Full/down/Unknown values
    _stale_keys = {
        "channels",
        "channels_online",
        "channels_offline",
        "channels_video_loss",
        "channels_recording",
        "channels_total",
        "nvr_logs",
        "hdd_list",
        "hdd_status",
        "hdd_count",
        "hdd_capacity_mb",
        "hdd_free_mb",
        "hdd_used_mb",
        "hdd_errors",
        "storage_ok",
        "storage_free_source",
        "health",
        "network_interface_status",
        "network_link_speed",
        "network_duplex",
        "network_addressing",
        "network_mac",
        "network_ok",
        "network_rx",
        "network_tx",
        "network_errors",
        "nvr_status",
        "system_state",
        "cpu_percent",
        "memory_percent",
        "memory_used",
        "memory_available",
        "memory_total",
        "temperature_c",
        "uptime",
        "uptime_seconds",
        "uptime_raw",
    }
    metrics: dict[str, Any] = {
        k: v
        for k, v in (device.last_metrics or {}).items()
        if k not in _stale_keys
    }
    ip = (device.ip_address or "").strip() if device.ip_address else ""
    username = (device.username or "").strip()
    password = device.password or ""
    brand = (device.manufacturer or device.model_number or "").lower()
    http_port = int(device.onvif_port or 80)

    if not ip:
        metrics["channels"] = _summarize_channels([])
        metrics["nvr_logs"] = []
        metrics["vendor_probe_error"] = "No IP configured"
        return metrics

    if not username:
        metrics["channels"] = _summarize_channels([])
        metrics["nvr_logs"] = []
        metrics["vendor_probe_error"] = "NVR username/password required to read channels & logs"
        return metrics

    try:
        if "dahua" in brand:
            metrics.update(
                probe_dahua_cgi(ip, username=username, password=password, http_port=http_port)
            )
        else:
            hik = probe_hikvision_isapi(
                ip, username=username, password=password, http_port=http_port
            )
            metrics.update(hik)
            # If ISAPI deviceInfo failed, try Dahua as fallback
            if not hik.get("device_info_ok") and not hik.get("channels_ok"):
                dahua = probe_dahua_cgi(
                    ip, username=username, password=password, http_port=http_port
                )
                # Prefer whichever returned channels
                if (dahua.get("channels") or {}).get("total", 0) > (
                    hik.get("channels") or {}
                ).get("total", 0):
                    metrics.update(dahua)
                elif not metrics.get("nvr_logs") and dahua.get("nvr_logs"):
                    metrics["nvr_logs"] = dahua["nvr_logs"]
                    metrics["nvr_logs_count"] = len(dahua["nvr_logs"])
    except Exception as exc:
        metrics["vendor_probe_error"] = str(exc)[:200]

    metrics.setdefault("channels", _summarize_channels([]))
    metrics.setdefault("nvr_logs", [])
    metrics.setdefault("device_model", device.model_number or device.manufacturer)
    if device.serial_number:
        metrics.setdefault("serial_number", device.serial_number)
    metrics["nvr_name"] = device.name
    metrics["ip_address"] = ip
    metrics["polled_at_ts"] = time.time()
    metrics["channels_source"] = "nvr"

    # Persist every fetched log into DB (accumulates full history)
    try:
        created = persist_nvr_logs(device, metrics.get("nvr_logs") or [])
        metrics["nvr_logs_saved"] = created
        from .models import InfraNvrLog

        metrics["nvr_logs_count"] = InfraNvrLog.objects.filter(device=device).count()
        # Keep last_metrics small — full log history lives in InfraNvrLog
        metrics["nvr_logs"] = []
    except Exception as exc:
        metrics["nvr_logs_persist_error"] = str(exc)[:200]
        metrics["nvr_logs"] = []

    # Always refresh from live device status (never keep stale "Unknown")
    if device.status == DeviceStatus.ONLINE:
        metrics["nvr_status"] = "Online"
    elif device.status == DeviceStatus.OFFLINE:
        metrics["nvr_status"] = "Offline"
    else:
        metrics["nvr_status"] = device.get_status_display() or "Unknown"
    if not metrics.get("system_state") or str(metrics.get("system_state")).lower() in (
        "unknown",
        "",
    ):
        metrics["system_state"] = "normal" if device.status == DeviceStatus.ONLINE else metrics["nvr_status"]

    # Reachable NVR cannot report hard-down NIC
    if device.status == DeviceStatus.ONLINE and str(
        metrics.get("network_interface_status") or ""
    ).lower() in ("down", "disconnect", "disconnected", "error", "fault"):
        metrics["network_interface_status"] = "up"

    # Normalize HDD rows + persist health scorecard for list/detail UIs
    if isinstance(metrics.get("hdd_list"), list):
        metrics["hdd_list"] = normalize_hdd_list(metrics["hdd_list"])
        metrics["hdd_count"] = len(metrics["hdd_list"])
    metrics["health"] = compute_nvr_health(
        metrics, device_status=str(device.status or metrics.get("nvr_status") or "")
    )

    return metrics


def build_nvr_detail_payload(device) -> dict[str, Any]:
    """Structured detail payload — channels & logs sourced from the NVR."""
    m = dict(device.last_metrics or {})
    channels = m.get("channels") if isinstance(m.get("channels"), dict) else _summarize_channels([])
    # Never fall back to TekEye camera sync for this payload
    if channels.get("source") != "nvr" and not channels.get("items"):
        channels = _summarize_channels([])
        channels["source"] = "nvr"
    status_label = device.get_status_display()
    # Always serve accumulated DB logs (all types) when available
    try:
        logs = load_stored_nvr_logs(device, limit=5000)
    except Exception:
        logs = m.get("nvr_logs") if isinstance(m.get("nvr_logs"), list) else []
    if not logs and isinstance(m.get("nvr_logs"), list):
        logs = m["nvr_logs"]

    uptime = _format_uptime(m.get("uptime_seconds"), m.get("uptime_raw") or m.get("uptime"))
    if not uptime:
        uptime = "—"

    # Sanitize / recompute RAM (Hikvision often stores used MB in memoryUsage)
    ram = m.get("memory_percent")
    try:
        if ram is not None and float(ram) > 100:
            ram = None
    except (TypeError, ValueError):
        ram = None
    if ram is None:
        used = _safe_float(m.get("memory_used"))
        avail = _safe_float(m.get("memory_available"))
        total = _safe_float(m.get("memory_total"))
        if used is not None and used > 100 and avail is not None and (used + avail) > 0:
            ram = _clamp_percent((used / (used + avail)) * 100)
            total = total or (used + avail)
        elif total and total > 0 and avail is not None:
            ram = _clamp_percent(((total - avail) / total) * 100)
        elif total and total > 0 and used is not None:
            ram = _clamp_percent((used / total) * 100)

    cpu = m.get("cpu_percent")
    try:
        if cpu is not None and float(cpu) > 100:
            cpu = None
    except (TypeError, ValueError):
        cpu = None

    # This firmware's /ISAPI/System/status has no CPUList / temperature nodes.
    system_probed = bool(
        m.get("system_status_ok")
        or m.get("uptime_seconds") is not None
        or m.get("memory_available") is not None
        or m.get("memory_percent") is not None
        or ram is not None
    )
    not_reported = "Not reported by NVR"

    hdd_list = normalize_hdd_list(m.get("hdd_list") if isinstance(m.get("hdd_list"), list) else [])
    # Sanitize stale wrong signals before scoring (online NVR ≠ NIC down / Unknown)
    iface = str(m.get("network_interface_status") or "").lower().strip()
    if device.status == "online" and iface in (
        "down",
        "disconnect",
        "disconnected",
        "error",
        "fault",
        "static",
        "dhcp",
        "dynamic",
    ):
        iface = "up"
    elif iface in ("static", "dhcp", "dynamic", ""):
        iface = "up" if device.status == "online" else ""
    nvr_status = status_label if device.status == "online" else (m.get("nvr_status") or status_label)
    if str(nvr_status).lower() in ("unknown", ""):
        nvr_status = status_label
    system_state = m.get("system_state") or "—"
    if str(system_state).lower() in ("unknown", "static", "dhcp"):
        system_state = "normal" if device.status == "online" else system_state

    health_metrics = {
        **m,
        "hdd_list": hdd_list,
        "channels": channels,
        "network_interface_status": iface or m.get("network_interface_status"),
        "nvr_status": nvr_status,
        "device_info_ok": m.get("device_info_ok") or device.status == "online",
        "network_ok": m.get("network_ok") or device.status == "online",
    }
    health = compute_nvr_health(health_metrics, device_status=str(device.status or ""))

    # Aggregate HDD status — prefer exact NVR wording when uniform
    hdd_status = m.get("hdd_status") or "—"
    if hdd_list:
        crit = sum(1 for h in hdd_list if h.get("level") == "critical")
        full = sum(1 for h in hdd_list if h.get("health_label") == "Full")
        sleep = sum(1 for h in hdd_list if h.get("health_label") == "Sleep")
        warn = sum(1 for h in hdd_list if h.get("level") == "warning")
        if crit:
            hdd_status = "error"
        elif sleep and sleep == warn and not full:
            hdd_status = "sleep"
        elif full and full == warn:
            hdd_status = "full"
        elif warn:
            hdd_status = "warning"
        else:
            hdd_status = "ok"

    cameras_nvr_id = resolve_cameras_nvr_id(device)
    # Enrich channel rows with logical channel for live preview / snapshot
    ch_items = list(channels.get("items") or [])
    for it in ch_items:
        raw_ch = it.get("channel") if it.get("channel") not in (None, "") else it.get("id")
        try:
            logical = int(str(raw_ch).strip())
        except (TypeError, ValueError):
            logical = None
        if logical is not None:
            it["channel"] = logical
            it["preview_channel"] = logical if logical < 100 else max(1, logical // 100)

    return {
        "id": device.id,
        "name": device.name,
        "status": device.status,
        "status_label": status_label,
        "ip_address": device.ip_address,
        "manufacturer": device.manufacturer,
        "model_number": device.model_number,
        "install_location": getattr(device, "install_location", "") or "",
        "source_key": getattr(device, "source_key", "") or "",
        "cameras_nvr_id": cameras_nvr_id,
        "last_polled_at": device.last_polled_at.isoformat() if device.last_polled_at else None,
        "last_error": device.last_error,
        "channels_source": m.get("channels_source") or channels.get("source") or "nvr",
        "vendor_probe_error": m.get("vendor_probe_error") or m.get("channels_error") or "",
        "health": health,
        "device_information": {
            "model": m.get("device_model") or device.model_number or device.manufacturer or "—",
            "firmware": m.get("firmware_version") or "—",
            "serial_number": m.get("serial_number") or device.serial_number or "—",
            "mac_address": m.get("mac_address") or device.mac_address or "—",
            "system_identifiers": m.get("device_name")
            or device.asset_tag
            or device.source_key
            or "—",
        },
        "system_health": {
            "nvr_status": nvr_status,
            "system_state": system_state,
            "cpu_usage": cpu,
            "cpu_display": (
                f"{cpu:.1f}%" if cpu is not None else (not_reported if system_probed else "—")
            ),
            "ram_usage": ram,
            "ram_display": (
                f"{ram:.1f}%" if ram is not None else (not_reported if system_probed else "—")
            ),
            "temperature": m.get("temperature_c"),
            "temperature_display": (
                f"{float(m['temperature_c']):.1f} °C"
                if m.get("temperature_c") is not None
                else (not_reported if system_probed else "—")
            ),
            "uptime": uptime,
        },
        "storage_health": {
            "hdd_status": hdd_status,
            "hdd_capacity": _mb_to_display(m.get("hdd_capacity_mb"))
            if m.get("hdd_capacity_mb") not in (None, "", 0, 0.0)
            else (m.get("hdd_capacity") or "—"),
            "used_space": (
                _mb_to_display(m.get("hdd_used_mb"))
                if m.get("hdd_used_mb") not in (None, "")
                else (m.get("hdd_used") or "—")
            ),
            "free_space": (
                _mb_to_display(m.get("hdd_free_mb"))
                if m.get("hdd_free_mb") not in (None, "")
                else (m.get("hdd_free") or "—")
            ),
            "disk_errors": m.get("hdd_errors") if m.get("hdd_errors") is not None else "—",
            "hdd_count": len(hdd_list),
            "hdd_list": hdd_list,
        },
        "network_health": {
            "interface_status": iface or ("up" if device.status == "online" else "—"),
            "link_speed": (
                m.get("network_link_speed")
                if m.get("network_link_speed") not in (None, "", "0", 0)
                else "—"
            ),
            "rx_traffic": m.get("network_rx") or m.get("rx_bytes") or "—",
            "tx_traffic": m.get("network_tx") or m.get("tx_bytes") or "—",
            "network_errors": m.get("network_errors")
            if m.get("network_errors") not in (None, "")
            else "—",
            "duplex": m.get("network_duplex") or "—",
            "addressing": m.get("network_addressing") or "—",
        },
        "recording": {
            "recording_status": m.get("recording_status") or "—",
            "recording_alarms": m.get("recording_alarms") or m.get("alarms") or "—",
        },
        "camera_channels": {**channels, "items": ch_items},
        "nvr_logs": logs,
        "nvr_logs_count": len(logs),
        "alarms": {
            "storage": m.get("alarm_storage") or "—",
            "network": m.get("alarm_network") or "—",
            "hardware": m.get("alarm_hardware") or "—",
            "other": m.get("alarms") or "—",
        },
        "raw_metrics": m,
    }
