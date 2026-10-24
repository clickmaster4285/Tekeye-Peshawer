"""Record a video clip whenever objects move on a live camera.

Inference (≈1 fps per camera under full load) only tells us WHEN objects start and stop
moving; the video itself is sampled straight from each camera's latest-frame buffer at
ML_MOTION_CLIP_FPS. Each camera keeps ML_MOTION_PREROLL_SEC of frames; a motion "start"
opens a recording that begins with that pre-roll and runs while anything on the camera
moves (+ post-roll), at least ML_MOTION_CLIP_MIN_SEC and at most ML_MOTION_CLIP_MAX_SEC.
Objects still moving at the cap continue in a new part.

Finished clips are written to ML_MOTION_CLIP_DIR as <id>.mp4 + <id>.jpg (poster, when the
motion was confirmed) + <id>.end.jpg (last frame) + <id>.json (written last = ready).
The backend pulls them via /live/motion/clips and deletes them here once stored.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

CLIP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")

# camera key → stream object with get_latest() -> (frame | None, seq)
FrameSources = Callable[[], dict[str, Any]]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ClipConfig:
    enabled: bool = True
    fps: float = 8.0
    preroll_sec: float = 5.0
    postroll_sec: float = 2.0
    min_sec: float = 10.0
    max_sec: float = 30.0
    # Wait after a clip ends before a new one may start on that camera (0 = none)
    cooldown_sec: float = 0.0
    max_width: int = 1280
    jpeg_quality: int = 80
    crf: int = 28
    # Oldest clips are dropped when the backend has not collected them and this fills up
    max_pending_mb: float = 2048.0
    out_dir: str = ""

    @classmethod
    def from_env(cls) -> ClipConfig:
        default_dir = str(Path(__file__).resolve().parent / "motion_clips")
        return cls(
            enabled=os.getenv("ML_MOTION_CLIPS_ENABLED", "true").strip().lower() in ("true", "1", "yes"),
            fps=min(25.0, max(1.0, _env_float("ML_MOTION_CLIP_FPS", 8.0))),
            preroll_sec=max(0.0, _env_float("ML_MOTION_PREROLL_SEC", 5.0)),
            postroll_sec=max(0.0, _env_float("ML_MOTION_POSTROLL_SEC", 2.0)),
            min_sec=max(1.0, _env_float("ML_MOTION_CLIP_MIN_SEC", 10.0)),
            max_sec=max(2.0, _env_float("ML_MOTION_CLIP_MAX_SEC", 30.0)),
            cooldown_sec=max(0.0, _env_float("ML_MOTION_CLIP_COOLDOWN_SEC", 0.0)),
            max_width=max(320, int(_env_float("ML_MOTION_CLIP_WIDTH", 1280))),
            jpeg_quality=min(95, max(40, int(_env_float("ML_MOTION_CLIP_JPEG_QUALITY", 80)))),
            crf=min(40, max(18, int(_env_float("ML_MOTION_CLIP_CRF", 28)))),
            max_pending_mb=max(100.0, _env_float("ML_MOTION_CLIP_MAX_PENDING_MB", 2048.0)),
            out_dir=os.getenv("ML_MOTION_CLIP_DIR", "").strip() or default_dir,
        )


@dataclass
class _Movement:
    track_id: int
    global_object_id: str
    class_name: str
    started_at: float
    from_bbox: list[float]
    to_bbox: list[float]
    ended_at: float | None = None
    still_moving: bool = True


@dataclass
class _Recording:
    camera_key: str
    started_at: float
    part: int
    frames: list[tuple[float, bytes]] = field(default_factory=list)
    movements: dict[int, _Movement] = field(default_factory=dict)
    poster_at: float = 0.0
    last_motion_at: float = 0.0
    source_size: tuple[int, int] = (0, 0)
    clip_size: tuple[int, int] = (0, 0)

    def moving(self) -> list[_Movement]:
        return [m for m in self.movements.values() if m.still_moving]


@dataclass
class _Camera:
    ring: deque[tuple[float, bytes]] = field(default_factory=deque)
    recording: _Recording | None = None
    cooldown_until: float = 0.0
    last_seq: int = -1
    new_frames: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    source_size: tuple[int, int] = (0, 0)
    clip_size: tuple[int, int] = (0, 0)


class MotionClipRecorder:
    """Sampler thread: motion events + camera frames → recordings. Encoder thread: MP4 files."""

    def __init__(
        self,
        config: ClipConfig | None = None,
        *,
        ffmpeg_path: Callable[[], str | None] | None = None,
        frame_sources: FrameSources | None = None,
    ):
        self.config = config or ClipConfig.from_env()
        self._ffmpeg_path = ffmpeg_path or (lambda: None)
        self._frame_sources = frame_sources or (lambda: {})
        self._dir = Path(self.config.out_dir)
        self._cameras: dict[str, _Camera] = {}
        self._lock = threading.Lock()
        self._events: queue.Queue = queue.Queue(maxsize=512)
        self._encode: queue.Queue = queue.Queue(maxsize=32)
        self._threads: list[threading.Thread] = []
        self._running = False
        self.stats = {"events_dropped": 0, "clips_written": 0, "clips_failed": 0, "clips_pruned": 0}

    # ── lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        if not self.config.enabled or self._running:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        for target, name in ((self._sample_loop, "motion-clip-sampler"), (self._encode_loop, "motion-clip-encode")):
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)
        print(
            f"[motion-clip] Recording to {self._dir} ({self.config.fps} fps, pre-roll {self.config.preroll_sec}s, "
            f"{self.config.min_sec}-{self.config.max_sec}s per clip)"
        )

    def stop(self) -> None:
        self._running = False

    def reset(self, camera_key: str) -> None:
        with self._lock:
            self._cameras.pop(camera_key, None)

    # ── input from the inference loop (must stay cheap) ───────

    def submit(self, camera_key: str, detections: list[dict[str, Any]], events: list[dict[str, Any]], now: float) -> None:
        """Motion events + current boxes for one inferred frame."""
        if not self._running:
            return
        moving = [d for d in detections if d.get("motion_state") == "moving" and d.get("track_id") is not None]
        if not events and not moving:
            return
        try:
            self._events.put_nowait((camera_key, moving, events, now))
        except queue.Full:
            self.stats["events_dropped"] += 1

    # ── sampler thread ────────────────────────────────────────

    def _sample_loop(self) -> None:
        interval = 1.0 / self.config.fps
        next_at = time.monotonic()
        while self._running:
            self._drain_events()
            now = time.time()
            try:
                sources = self._frame_sources()
            except Exception:
                sources = {}
            for key, stream in sources.items():
                try:
                    frame, seq = stream.get_latest()
                except Exception:
                    continue
                if frame is None:
                    continue
                with self._lock:
                    cam = self._cameras.setdefault(key, _Camera())
                    if seq == cam.last_seq:
                        continue
                    cam.last_seq = seq
                    cam.new_frames.append(now)
                try:
                    self.add_frame(key, frame, now)
                except Exception as exc:
                    print(f"[motion-clip] Frame error [{key}]: {exc}")
            self.check_all(time.time())
            next_at += interval
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_at = time.monotonic()  # fell behind: don't try to catch up

    def _drain_events(self) -> None:
        while True:
            try:
                camera_key, moving, events, now = self._events.get_nowait()
            except queue.Empty:
                return
            self.on_motion(camera_key, moving, events, now)

    def on_motion(self, camera_key: str, moving_dets: list[dict[str, Any]], events: list[dict[str, Any]], now: float) -> None:
        with self._lock:
            cam = self._cameras.setdefault(camera_key, _Camera())
            rec = cam.recording
            for ev in events:
                rec = self._apply_event(cam, camera_key, ev, now)
            if rec is None:
                return
            by_track = {int(d["track_id"]): d for d in moving_dets}
            for mv in rec.moving():
                det = by_track.get(mv.track_id)
                if det and det.get("bbox"):
                    mv.to_bbox = [float(v) for v in det["bbox"][:4]]
            if rec.moving():
                rec.last_motion_at = now

    def add_frame(self, camera_key: str, frame: np.ndarray, now: float) -> None:
        cfg = self.config
        src_h, src_w = frame.shape[:2]
        scale = min(1.0, cfg.max_width / float(src_w)) if src_w else 1.0
        if scale < 1.0:
            img = cv2.resize(frame, (int(src_w * scale) // 2 * 2, int(src_h * scale) // 2 * 2), interpolation=cv2.INTER_AREA)
        else:
            img = frame[: src_h // 2 * 2, : src_w // 2 * 2]  # libx264 / yuv420p need even sizes
        ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cfg.jpeg_quality])
        if not ok:
            return
        data = jpeg.tobytes()
        with self._lock:
            cam = self._cameras.setdefault(camera_key, _Camera())
            cam.source_size = (src_w, src_h)
            cam.clip_size = (img.shape[1], img.shape[0])
            cam.ring.append((now, data))
            while cam.ring and now - cam.ring[0][0] > cfg.preroll_sec:
                cam.ring.popleft()
            rec = cam.recording
            if rec is not None:
                if not rec.frames:
                    # First frame of a new recording: seed it with the pre-roll
                    rec.frames = [f for f in cam.ring if f[0] >= rec.started_at]
                else:
                    rec.frames.append((now, data))
                rec.source_size, rec.clip_size = cam.source_size, cam.clip_size
            self._check_camera(camera_key, cam, now)

    def _apply_event(self, cam: _Camera, camera_key: str, ev: dict[str, Any], now: float) -> _Recording | None:
        """Caller holds self._lock."""
        rec = cam.recording
        tid = int(ev.get("track_id") or 0)
        kind = ev.get("event")
        if kind == "start":
            if rec is None:
                if now < cam.cooldown_until:
                    return None
                # Motion began ~start_sec before it was confirmed; the ring covers the pre-roll
                rec = _Recording(
                    camera_key=camera_key,
                    started_at=now - self.config.preroll_sec,
                    part=1,
                    poster_at=now,
                    last_motion_at=now,
                )
                cam.recording = rec
            if tid not in rec.movements or not rec.movements[tid].still_moving:
                rec.movements[tid] = _Movement(
                    track_id=tid,
                    global_object_id=str(ev.get("global_object_id") or ""),
                    class_name=str(ev.get("class_name") or ""),
                    started_at=float(ev.get("at") or now),
                    from_bbox=list(ev.get("from_bbox") or []),
                    to_bbox=list(ev.get("to_bbox") or []),
                )
            rec.last_motion_at = now
        elif rec is not None and kind in ("stop", "lost") and tid in rec.movements:
            mv = rec.movements[tid]
            mv.still_moving = False
            mv.ended_at = float(ev.get("at") or now)
            mv.to_bbox = list(ev.get("to_bbox") or mv.to_bbox)
            if ev.get("global_object_id"):
                mv.global_object_id = str(ev["global_object_id"])
        return rec

    # ── finishing recordings ──────────────────────────────────

    def check_all(self, now: float) -> None:
        with self._lock:
            for key, cam in self._cameras.items():
                self._check_camera(key, cam, now)

    def _check_camera(self, camera_key: str, cam: _Camera, now: float) -> None:
        """Caller holds self._lock."""
        rec = cam.recording
        if rec is None or not rec.frames:
            return
        cfg = self.config
        # Measured from the first frame actually recorded (the ring may be shorter than the pre-roll)
        length = now - rec.frames[0][0]
        capped = length >= cfg.max_sec
        quiet = not rec.moving() and now - rec.last_motion_at >= cfg.postroll_sec and length >= cfg.min_sec
        if not (capped or quiet):
            return
        cam.recording = None
        cam.cooldown_until = now + cfg.cooldown_sec
        still = rec.moving()
        if capped and still:
            # Same movement continues in the next part (no cooldown between parts)
            nxt = _Recording(camera_key=camera_key, started_at=now, part=rec.part + 1, poster_at=now, last_motion_at=now)
            for mv in still:
                nxt.movements[mv.track_id] = _Movement(
                    track_id=mv.track_id,
                    global_object_id=mv.global_object_id,
                    class_name=mv.class_name,
                    started_at=now,
                    from_bbox=list(mv.to_bbox),
                    to_bbox=list(mv.to_bbox),
                )
            cam.recording = nxt
            cam.cooldown_until = 0.0
        try:
            self._encode.put_nowait(rec)
        except queue.Full:
            self.stats["clips_failed"] += 1
            print(f"[motion-clip] Encode queue full — dropped clip [{camera_key}]")

    # ── encode thread: MP4 + poster + metadata ────────────────

    def _encode_loop(self) -> None:
        while self._running:
            try:
                rec = self._encode.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.write_clip(rec)
                self._prune()
            except Exception as exc:
                self.stats["clips_failed"] += 1
                print(f"[motion-clip] Write failed [{rec.camera_key}]: {exc}")

    def write_clip(self, rec: _Recording) -> None:
        frames = rec.frames
        if len(frames) < 2:
            return
        ffmpeg = self._ffmpeg_path()
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found")
        duration = max(0.5, frames[-1][0] - frames[0][0])
        fps = max(1.0, (len(frames) - 1) / duration)
        safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", rec.camera_key)
        clip_id = f"{safe_key}-{int(frames[0][0] * 1000)}-{uuid.uuid4().hex[:6]}"
        mp4 = self._dir / f"{clip_id}.mp4"
        tmp = self._dir / f"{clip_id}.part.mp4"
        cmd = [
            ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "image2pipe", "-framerate", f"{fps:.3f}", "-c:v", "mjpeg", "-i", "-",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(self.config.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", str(tmp),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ts, data in frames:
                proc.stdin.write(data)
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace")
            code = proc.wait(timeout=120)
        except Exception:
            proc.kill()
            tmp.unlink(missing_ok=True)
            raise
        finally:
            proc.stderr.close()
        if code != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg exit {code}: {err.strip()[:300]}")
        tmp.replace(mp4)

        poster = min(frames, key=lambda f: abs(f[0] - rec.poster_at))[1]
        (self._dir / f"{clip_id}.jpg").write_bytes(poster)
        (self._dir / f"{clip_id}.end.jpg").write_bytes(frames[-1][1])

        movements = [
            {
                "track_id": mv.track_id,
                "global_object_id": mv.global_object_id,
                "class_name": mv.class_name,
                "started_at": mv.started_at,
                "ended_at": mv.ended_at,
                "still_moving": mv.still_moving,
                "from_bbox": [round(v, 1) for v in mv.from_bbox],
                "to_bbox": [round(v, 1) for v in mv.to_bbox],
            }
            for mv in rec.movements.values()
        ]
        meta = {
            "clip_id": clip_id,
            "camera_key": rec.camera_key,
            "part": rec.part,
            "started_at": frames[0][0],
            "ended_at": frames[-1][0],
            "duration_sec": round(duration, 2),
            "frame_count": len(frames),
            "fps": round(fps, 2),
            "clip_width": rec.clip_size[0],
            "clip_height": rec.clip_size[1],
            "source_width": rec.source_size[0],
            "source_height": rec.source_size[1],
            "size_bytes": mp4.stat().st_size,
            "movements": movements,
        }
        tmp_meta = self._dir / f"{clip_id}.json.tmp"
        tmp_meta.write_text(json.dumps(meta), encoding="utf-8")
        tmp_meta.replace(self._dir / f"{clip_id}.json")
        self.stats["clips_written"] += 1
        objs = ", ".join(m["global_object_id"] or m["class_name"] for m in movements)
        print(f"[motion-clip] {rec.camera_key} saved {duration:.1f}s clip ({len(frames)} frames) — {objs}")

    def _prune(self) -> None:
        limit = self.config.max_pending_mb * 1024 * 1024
        clips = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in self._dir.glob("*") if p.is_file())
        while clips and total > limit:
            oldest = clips.pop(0)
            total -= self.delete_clip(oldest.stem)
            self.stats["clips_pruned"] += 1

    # ── pull API helpers ──────────────────────────────────────

    def _path(self, clip_id: str, suffix: str) -> Path | None:
        if not CLIP_ID_RE.match(clip_id or ""):
            return None
        return self._dir / f"{clip_id}{suffix}"

    def list_ready(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._dir.is_dir():
            return []
        out = []
        for meta in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[: max(1, limit)]:
            try:
                out.append(json.loads(meta.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def file_path(self, clip_id: str, kind: str) -> Path | None:
        suffix = {"video": ".mp4", "poster": ".jpg", "end": ".end.jpg"}.get(kind)
        path = self._path(clip_id, suffix) if suffix else None
        return path if path is not None and path.is_file() else None

    def delete_clip(self, clip_id: str) -> int:
        freed = 0
        for suffix in (".json", ".mp4", ".jpg", ".end.jpg"):
            path = self._path(clip_id, suffix)
            if path is not None and path.is_file():
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
        return freed

    def status(self) -> dict[str, Any]:
        with self._lock:
            recording = {
                key: {
                    "since": round(cam.recording.started_at, 2),
                    "part": cam.recording.part,
                    "frames": len(cam.recording.frames),
                    "moving": [m.global_object_id or m.class_name for m in cam.recording.moving()],
                }
                for key, cam in self._cameras.items()
                if cam.recording is not None
            }
            buffered = {key: len(cam.ring) for key, cam in self._cameras.items()}
            t = time.time()
            sampled = {
                key: round(sum(1 for x in cam.new_frames if t - x <= 30) / 30, 2) for key, cam in self._cameras.items()
            }
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "fps": self.config.fps,
            "dir": str(self._dir),
            "pending_clips": len(list(self._dir.glob("*.json"))) if self._dir.is_dir() else 0,
            "preroll_frames": buffered,
            "new_frames_per_sec": sampled,
            "recording": recording,
            "event_queue": self._events.qsize(),
            **self.stats,
        }
