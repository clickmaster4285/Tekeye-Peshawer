"""Run: python -m unittest test_motion_clips  (from ml_services/). Needs ffmpeg."""

import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from live_stream import _resolve_ffmpeg_path
from motion_clips import ClipConfig, MotionClipRecorder

FPS = 8.0  # sampled video frames per second
INFER_EVERY = 8  # inference (motion updates) about once per second


def frame(i: int) -> np.ndarray:
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    img[:, (i * 3) % 150 : (i * 3) % 150 + 10] = 255
    return img


def start(at: float, tid: int = 1, gid: str = "GV1") -> dict:
    return {"event": "start", "at": at, "track_id": tid, "global_object_id": gid, "class_name": "car",
            "from_bbox": [10, 10, 40, 40], "to_bbox": [20, 10, 50, 40]}


def stop(at: float, tid: int = 1, gid: str = "GV1") -> dict:
    return {"event": "stop", "at": at, "track_id": tid, "global_object_id": gid, "class_name": "car",
            "from_bbox": [10, 10, 40, 40], "to_bbox": [100, 10, 130, 40]}


@unittest.skipUnless(_resolve_ffmpeg_path(), "ffmpeg not installed")
class MotionClipRecorderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="motion-clips-")
        cfg = ClipConfig(fps=FPS, preroll_sec=5.0, postroll_sec=2.0, min_sec=10.0, max_sec=30.0, out_dir=self.dir)
        self.rec = MotionClipRecorder(cfg, ffmpeg_path=_resolve_ffmpeg_path)
        self.t = 1000.0
        self.i = 0
        self.moving: set[int] = set()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_for(self, seconds: float, events_at: dict | None = None):
        """Feed video frames at FPS; motion updates every INFER_EVERY frames; events_at: frame offset → events."""
        events_at = events_at or {}
        for n in range(int(seconds * FPS)):
            events = events_at.get(n, [])
            for ev in events:
                (self.moving.add if ev["event"] == "start" else self.moving.discard)(ev["track_id"])
            if events or n % INFER_EVERY == 0:
                dets = [{"track_id": tid, "class_name": "car", "motion_state": "moving", "bbox": [10 + n, 10, 40 + n, 40]}
                        for tid in self.moving]
                self.rec.on_motion("cam-5", dets, events, self.t)
            self.rec.add_frame("cam-5", frame(self.i), self.t)
            self.t += 1 / FPS
            self.i += 1

    def flush(self) -> list[dict]:
        while not self.rec._encode.empty():
            self.rec.write_clip(self.rec._encode.get())
        return self.rec.list_ready()

    def test_short_movement_gives_one_clip_of_at_least_10s_with_preroll(self):
        self.run_for(8)  # parked: fills pre-roll, nothing recorded
        self.assertEqual(self.flush(), [])
        t0 = self.t
        self.run_for(20, {0: [start(t0 - 1)], 16: [stop(t0 + 2)]})  # moves ~2 s
        clips = self.flush()
        self.assertEqual(len(clips), 1)
        c = clips[0]
        self.assertGreaterEqual(c["duration_sec"], 10.0)
        self.assertLess(c["duration_sec"], 14)
        self.assertLessEqual(c["started_at"], t0 - 4.5)  # 5 s pre-roll
        self.assertAlmostEqual(c["fps"], FPS, delta=0.5)
        self.assertEqual(c["camera_key"], "cam-5")
        mv = c["movements"][0]
        self.assertEqual((mv["global_object_id"], mv["still_moving"]), ("GV1", False))
        self.assertEqual(mv["to_bbox"][0], 100)
        cid = c["clip_id"]
        self.assertGreater(self.rec.file_path(cid, "video").stat().st_size, 0)
        self.assertTrue(self.rec.file_path(cid, "poster").is_file())
        self.assertTrue(self.rec.file_path(cid, "end").is_file())
        self.assertIsNone(self.rec.file_path(cid, "other"))
        self.assertGreater(self.rec.delete_clip(cid), 0)
        self.assertEqual(self.rec.list_ready(), [])

    def test_min_length_counts_from_first_recorded_frame(self):
        # Camera just connected: only 1 s in the pre-roll, motion stops at once
        self.run_for(1)
        t0 = self.t
        self.run_for(14, {0: [start(t0)], 1: [stop(t0 + 0.2)]})
        clips = self.flush()
        self.assertEqual(len(clips), 1)
        self.assertGreaterEqual(clips[0]["duration_sec"], 10.0)

    def test_long_movement_is_split_at_30s(self):
        self.run_for(1)
        self.run_for(70, {0: [start(self.t)]})
        clips = self.flush()
        self.assertEqual([c["part"] for c in clips], [1, 2])
        self.assertTrue(all(c["duration_sec"] <= 30.5 for c in clips))
        second = clips[1]["movements"][0]
        self.assertTrue(second["still_moving"])
        self.assertEqual(second["global_object_id"], "GV1")
        # Part 2 starts where part 1 left the object
        self.assertEqual(second["from_bbox"], clips[0]["movements"][0]["to_bbox"])

    def test_two_objects_moving_together_share_one_clip(self):
        self.run_for(6)
        t0 = self.t
        self.run_for(20, {0: [start(t0)], 3: [start(t0, tid=2, gid="GP4")], 16: [stop(t0 + 2), stop(t0 + 2, tid=2, gid="GP4")]})
        clips = self.flush()
        self.assertEqual(len(clips), 1)
        self.assertEqual(sorted(m["global_object_id"] for m in clips[0]["movements"]), ["GP4", "GV1"])

    def test_bad_clip_ids_are_rejected(self):
        self.assertIsNone(self.rec.file_path("../../etc/passwd", "video"))
        self.assertEqual(self.rec.delete_clip("..\\x"), 0)

    def test_metadata_is_valid_json_on_disk(self):
        self.run_for(1)
        self.run_for(15, {0: [start(self.t)], 3: [stop(self.t + 0.5)]})
        clips = self.flush()
        meta = json.loads((Path(self.dir) / f"{clips[0]['clip_id']}.json").read_text())
        self.assertEqual((meta["source_width"], meta["clip_width"]), (160, 160))


class FakeStream:
    def __init__(self):
        self.seq = 0
        self.lock = threading.Lock()

    def get_latest(self):
        with self.lock:
            return frame(self.seq), self.seq


class SamplerThreadTests(unittest.TestCase):
    def test_sampler_reads_new_frames_only(self):
        tmp = tempfile.mkdtemp(prefix="motion-clips-")
        self.addCleanup(shutil.rmtree, tmp, True)
        stream = FakeStream()
        rec = MotionClipRecorder(
            ClipConfig(fps=20.0, out_dir=tmp), ffmpeg_path=_resolve_ffmpeg_path, frame_sources=lambda: {"cam-1": stream}
        )
        rec.start()
        try:
            time.sleep(0.4)
            self.assertEqual(rec.status()["preroll_frames"], {"cam-1": 1})  # same seq → kept once
            for _ in range(3):
                with stream.lock:
                    stream.seq += 1
                time.sleep(0.15)
            self.assertEqual(rec.status()["preroll_frames"]["cam-1"], 4)
        finally:
            rec.stop()


if __name__ == "__main__":
    unittest.main()
