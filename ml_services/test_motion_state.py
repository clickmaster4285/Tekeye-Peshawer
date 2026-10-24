"""Run: python -m unittest test_motion_state  (from ml_services/)."""

import unittest

from motion_state import MOVING, STATIONARY, CameraMotionTracker, MotionConfig

CFG = MotionConfig(move_frac=0.15, scale_frac=0.30, start_sec=1.0, still_frac=0.05, stop_sec=3.0, track_ttl_sec=10.0)
FPS = 6.0  # live inference runs ~every 0.15 s


def det(x: float, y: float = 100.0, w: float = 100.0, h: float = 100.0, tid: int = 1) -> dict:
    return {"track_id": tid, "class_name": "car", "bbox": [x, y, x + w, y + h], "global_object_id": "GV1"}


class MotionStateTests(unittest.TestCase):
    def setUp(self):
        self.tracker = CameraMotionTracker("cam-1", CFG)
        self.t = 1000.0
        self.events: list[dict] = []

    def feed(self, positions, *, step: float = 1 / FPS, **kw) -> dict:
        d = {}
        for x in positions:
            d = det(x, **kw)
            self.events += self.tracker.update([d], self.t)
            self.t += step
        return d

    def kinds(self) -> list[str]:
        return [e["event"] for e in self.events]

    def test_parked_object_with_jitter_never_moves(self):
        d = self.feed([100 + (i % 3) * 4 for i in range(300)])  # ±4 px on a 100 px box, 50 s
        self.assertEqual(self.kinds(), [])
        self.assertEqual(d["motion_state"], STATIONARY)

    def test_short_bump_is_ignored(self):
        self.feed([100] * 10)
        self.feed([130] * 3)  # 0.5 s away, then back
        self.feed([100] * 20)
        self.assertEqual(self.kinds(), [])

    def test_move_then_park_gives_start_and_stop(self):
        self.feed([100] * 10)
        moving_from = self.t
        d = self.feed([100 + i * 10 for i in range(1, 31)])  # drives 300 px over 5 s
        self.assertEqual(d["motion_state"], MOVING)
        self.assertEqual(self.kinds(), ["start"])
        # Start time is when it first left the anchor, not when confirmed 1 s later
        self.assertLess(self.events[0]["at"], moving_from + 1.0)

        d = self.feed([400] * 30)  # parked 5 s
        self.assertEqual(self.kinds(), ["start", "stop"])
        self.assertEqual(d["motion_state"], STATIONARY)
        stop = self.events[1]
        self.assertEqual(stop["from_bbox"][0], 100)
        self.assertEqual(stop["to_bbox"][0], 400)
        self.assertEqual(stop["distance_px"], 300)
        self.assertEqual(stop["global_object_id"], "GV1")
        self.assertGreater(stop["duration_sec"], 4)

        # New resting place is the anchor: jitter there does not restart motion
        self.feed([400 + (i % 2) * 4 for i in range(60)])
        self.assertEqual(self.kinds(), ["start", "stop"])

    def test_approaching_camera_counts_as_motion(self):
        self.feed([100] * 10)
        # Same center, box grows 100 → 180 px over ~2.7 s
        for i in range(1, 17):
            size = 100 + i * 5
            off = 100 - (size - 100) / 2
            self.events += self.tracker.update([det(off, y=off, w=size, h=size)], self.t)
            self.t += 1 / FPS
        self.assertEqual(self.kinds(), ["start"])

    def test_object_leaving_while_moving_ends_as_lost(self):
        self.feed([100] * 10)
        self.feed([100 + i * 10 for i in range(1, 13)])
        self.assertEqual(self.kinds(), ["start"])
        self.t += 11.0
        self.events += self.tracker.update([], self.t)
        self.assertEqual(self.kinds(), ["start", "lost"])
        self.assertEqual(self.tracker.track_count(), 0)

    def test_faces_and_plates_are_ignored(self):
        for i in range(30):
            dets = [
                {"track_id": 7, "class_name": "face", "bbox": [100 + i * 10, 100, 150 + i * 10, 150]},
                {"track_id": 8, "class_name": "License_Plate", "bbox": [100 + i * 10, 300, 160 + i * 10, 320]},
            ]
            self.events += self.tracker.update(dets, self.t)
            self.t += 1 / FPS
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.tracker.track_count(), 0)
        self.assertNotIn("motion_state", dets[0])

    def test_detections_without_track_or_box_are_skipped(self):
        dets = [{"class_name": "car", "bbox": [0, 0, 10, 10]}, {"track_id": 5, "bbox": None}]
        self.assertEqual(self.tracker.update(dets, self.t), [])
        self.assertNotIn("motion_state", dets[0])
        self.assertEqual(self.tracker.track_count(), 0)


if __name__ == "__main__":
    unittest.main()
