"""Per-object moving / stationary state from ByteTrack boxes (live cameras).

An object is "moving" once its box has left its resting position (anchor) by more
than ML_MOTION_MOVE_FRAC of its size for ML_MOTION_START_SEC, and "stationary" again
after ML_MOTION_STOP_SEC without leaving a small still-zone. Start / stop events are
logged and kept for /live/motion/status; clip recording builds on them later.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

MOVING = "moving"
STATIONARY = "stationary"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MotionConfig:
    enabled: bool = True
    # Center shift (fraction of box size) or size change that counts as leaving the anchor
    move_frac: float = 0.15
    scale_frac: float = 0.30
    # Must stay away from the anchor this long before it is "moving" (filters jitter)
    start_sec: float = 1.0
    # Still-zone while moving; no exit from it for stop_sec → "stationary"
    still_frac: float = 0.05
    stop_sec: float = 3.0
    # Forget a track not seen for this long (ends its motion as "lost")
    track_ttl_sec: float = 10.0
    log_events: bool = True
    # Parts of another object (face, plate) or shapes that never stand still (smoke, fire)
    exclude_classes: frozenset[str] = frozenset({"face", "license_plate", "smoke", "fire", "flame"})

    @classmethod
    def from_env(cls) -> MotionConfig:
        return cls(
            enabled=os.getenv("ML_MOTION_ENABLED", "true").strip().lower() in ("true", "1", "yes"),
            move_frac=max(0.01, _env_float("ML_MOTION_MOVE_FRAC", 0.15)),
            scale_frac=max(0.05, _env_float("ML_MOTION_SCALE_FRAC", 0.30)),
            start_sec=max(0.0, _env_float("ML_MOTION_START_SEC", 1.0)),
            still_frac=max(0.005, _env_float("ML_MOTION_STILL_FRAC", 0.05)),
            stop_sec=max(0.5, _env_float("ML_MOTION_STOP_SEC", 3.0)),
            track_ttl_sec=max(1.0, _env_float("ML_MOTION_TRACK_TTL_SEC", 10.0)),
            log_events=os.getenv("ML_MOTION_LOG", "true").strip().lower() in ("true", "1", "yes"),
            exclude_classes=frozenset(
                c.strip().lower()
                for c in os.getenv("ML_MOTION_EXCLUDE_CLASSES", "face,license_plate,smoke,fire,flame").split(",")
                if c.strip()
            ),
        )


def _bbox4(det: dict[str, Any]) -> list[float] | None:
    bbox = det.get("bbox")
    if not bbox or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _center(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def _size(b: list[float]) -> float:
    return max(1.0, math.sqrt((b[2] - b[0]) * (b[3] - b[1])))


def _shift(ref: list[float], cur: list[float]) -> tuple[float, float]:
    """(center shift / ref size, |size change| / ref size)."""
    (rx, ry), (cx, cy) = _center(ref), _center(cur)
    size = _size(ref)
    return math.hypot(cx - rx, cy - ry) / size, abs(_size(cur) - size) / size


@dataclass
class _Track:
    track_id: int
    class_name: str
    anchor: list[float]
    last_bbox: list[float]
    last_seen: float
    state: str = STATIONARY
    state_since: float = 0.0
    global_object_id: str = ""
    # Candidate start: first time the box left the anchor (cleared if it returns)
    away_since: float | None = None
    # While moving: still-zone center box and when the object last left it
    still_ref: list[float] = field(default_factory=list)
    last_move_at: float = 0.0
    motion_from: list[float] = field(default_factory=list)


class CameraMotionTracker:
    """Motion state for every track on one camera. Not thread-safe; owner serializes calls."""

    def __init__(self, camera_key: str, config: MotionConfig):
        self.camera_key = camera_key
        self.config = config
        self._tracks: dict[int, _Track] = {}
        self._update_times: deque[float] = deque(maxlen=200)

    def update(self, detections: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        """Annotate detections with motion_state / motion_since; return start/stop/lost events."""
        cfg = self.config
        self._update_times.append(now)
        events: list[dict[str, Any]] = []
        seen: set[int] = set()
        for det in detections:
            tid = det.get("track_id")
            bbox = _bbox4(det)
            if tid is None or bbox is None:
                continue
            if str(det.get("class_name") or det.get("label") or "").strip().lower() in cfg.exclude_classes:
                continue
            tid = int(tid)
            seen.add(tid)
            tr = self._tracks.get(tid)
            if tr is None:
                tr = _Track(
                    track_id=tid,
                    class_name=str(det.get("class_name") or det.get("label") or "object").strip().lower(),
                    anchor=bbox,
                    last_bbox=bbox,
                    last_seen=now,
                    state_since=now,
                )
                self._tracks[tid] = tr
            if det.get("global_object_id"):
                tr.global_object_id = str(det["global_object_id"])
            tr.last_bbox = bbox
            tr.last_seen = now

            if tr.state == STATIONARY:
                shift, scale = _shift(tr.anchor, bbox)
                if shift > cfg.move_frac or scale > cfg.scale_frac:
                    if tr.away_since is None:
                        tr.away_since = now
                    if now - tr.away_since >= cfg.start_sec:
                        events.append(self._start(tr, now))
                else:
                    tr.away_since = None
            else:
                shift, scale = _shift(tr.still_ref, bbox)
                if shift > cfg.still_frac or scale > cfg.still_frac * 2:
                    tr.still_ref = bbox
                    tr.last_move_at = now
                elif now - tr.last_move_at >= cfg.stop_sec:
                    events.append(self._stop(tr, now, kind="stop"))

            det["motion_state"] = tr.state
            det["motion_since"] = tr.state_since

        for tid in [t for t, tr in self._tracks.items() if t not in seen and now - tr.last_seen > cfg.track_ttl_sec]:
            tr = self._tracks.pop(tid)
            if tr.state == MOVING:
                events.append(self._stop(tr, tr.last_seen, kind="lost"))
        return events

    def _start(self, tr: _Track, now: float) -> dict[str, Any]:
        # Movement began when the box first left the anchor, not when it was confirmed
        started = tr.away_since if tr.away_since is not None else now
        tr.state = MOVING
        tr.state_since = started
        tr.motion_from = tr.anchor
        tr.still_ref = tr.last_bbox
        tr.last_move_at = now
        tr.away_since = None
        return self._event(tr, "start", started, from_bbox=tr.motion_from, to_bbox=tr.last_bbox)

    def _stop(self, tr: _Track, now: float, *, kind: str) -> dict[str, Any]:
        started = tr.state_since
        tr.state = STATIONARY
        tr.state_since = now
        tr.anchor = tr.last_bbox
        tr.away_since = None
        event = self._event(tr, kind, now, from_bbox=tr.motion_from, to_bbox=tr.last_bbox)
        event["motion_started_at"] = started
        event["duration_sec"] = round(max(0.0, now - started), 2)
        return event

    def _event(self, tr: _Track, kind: str, at: float, *, from_bbox: list[float], to_bbox: list[float]) -> dict[str, Any]:
        (fx, fy), (tx, ty) = _center(from_bbox), _center(to_bbox)
        return {
            "camera_key": self.camera_key,
            "event": kind,
            "at": at,
            "track_id": tr.track_id,
            "global_object_id": tr.global_object_id,
            "class_name": tr.class_name,
            "from_bbox": [round(v, 1) for v in from_bbox],
            "to_bbox": [round(v, 1) for v in to_bbox],
            "distance_px": round(math.hypot(tx - fx, ty - fy), 1),
        }

    def moving_count(self) -> int:
        return sum(1 for tr in self._tracks.values() if tr.state == MOVING)

    def track_count(self) -> int:
        return len(self._tracks)

    def updates_per_sec(self, now: float, window: float = 30.0) -> float:
        """How often inference fed this camera recently (motion can only be seen this often)."""
        recent = [t for t in self._update_times if now - t <= window]
        return round(len(recent) / window, 2)


class MotionRegistry:
    """All cameras' motion trackers plus a short history of events for status/debugging."""

    def __init__(self, config: MotionConfig | None = None, *, history: int = 200):
        self.config = config or MotionConfig.from_env()
        self._cameras: dict[str, CameraMotionTracker] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = threading.Lock()

    def update(self, camera_key: str, detections: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        now = time.time() if now is None else now
        with self._lock:
            tracker = self._cameras.get(camera_key)
            if tracker is None:
                tracker = self._cameras[camera_key] = CameraMotionTracker(camera_key, self.config)
            events = tracker.update(detections, now)
            self._events.extend(events)
        if self.config.log_events:
            for ev in events:
                extra = f" after {ev['duration_sec']}s" if "duration_sec" in ev else ""
                obj = ev["global_object_id"] or f"track {ev['track_id']}"
                print(
                    f"[motion] {ev['camera_key']} {ev['class_name']} {obj} {ev['event']}{extra}"
                    f" moved {ev['distance_px']}px"
                )
        return events

    def reset(self, camera_key: str = "") -> None:
        with self._lock:
            if camera_key:
                self._cameras.pop(camera_key, None)
            else:
                self._cameras.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "config": self.config.__dict__,
                "cameras": {
                    key: {
                        "tracks": t.track_count(),
                        "moving": t.moving_count(),
                        "inferences_per_sec": t.updates_per_sec(time.time()),
                    }
                    for key, t in sorted(self._cameras.items())
                },
                "recent_events": list(self._events)[-50:],
            }
