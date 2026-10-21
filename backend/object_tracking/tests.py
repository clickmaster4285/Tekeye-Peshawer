"""One snapshot per visit: stationary objects, slow polls, flickers, look-alikes in the same spot."""

from datetime import timedelta
from itertools import count
from unittest.mock import patch

import numpy as np
from django.test import TestCase
from django.utils import timezone

from cameras.models import Camera, Nvr, Site
from object_tracking.models import GlobalObject, ObjectVisit, VisitStatus
from object_tracking.services import (
    mark_detection_captured,
    record_camera_poll,
    upsert_global_object,
)

RNG = np.random.default_rng(5)
CAR_BOX = [100, 100, 300, 220]


def unit_vector():
    v = RNG.normal(size=32)
    return list(v / np.linalg.norm(v))


class ObjectCaptureTests(TestCase):
    def setUp(self):
        nvr = Nvr.objects.create(site=Site.objects.create(code="T", name="T"), name="N", ip_address="127.0.0.1")
        self.camera = Camera.objects.create(nvr=nvr, name="Gate", code="gate", channel=1)
        self.now = timezone.now()
        self.event_ids = count(1)
        self.track_ids = count(1)
        self.captures = 0

    def det(self, *, box=CAR_BOX, emb=None, cls="car", track_id=None, gid="", ml_age=None):
        d = {
            "class_name": cls,
            "label": cls,
            "confidence": 0.9,
            "bbox": list(box),
            "track_id": next(self.track_ids) if track_id is None else track_id,
            "global_object_id": gid,
            "reid_embedding": emb or [],
        }
        if ml_age is not None:
            d["first_seen"], d["last_seen"] = 1000.0, 1000.0 + ml_age
        return d

    def poll(self, dets, *, advance=35):
        """One worker poll of the camera, `advance` seconds after the previous one."""
        self.now += timedelta(seconds=advance)
        with patch("object_tracking.services.timezone.now", return_value=self.now):
            seen, tracks = set(), set()
            for d in dets:
                tracks.add(d["track_id"])
                obj, visit, capture = upsert_global_object(self.camera, d, claimed_visit_ids=seen)
                seen.add(visit.pk)
                if capture:
                    mark_detection_captured(obj, next(self.event_ids), visit=visit)
                    self.captures += 1
            record_camera_poll(self.camera, seen_visit_ids=seen, active_track_ids=tracks)

    def test_stationary_object_with_slow_polls_and_id_switches_is_captured_once(self):
        emb = unit_vector()
        # New tracker ID and new ML global ID every poll, 35 s apart — the old 20 s exit
        # grace turned each of these into a new visit and a new snapshot.
        for i in range(20):
            self.poll([self.det(emb=emb, gid=f"GV{900 + i}")])

        self.assertEqual(self.captures, 1)
        self.assertEqual(ObjectVisit.objects.count(), 1)
        self.assertEqual(GlobalObject.objects.count(), 1)
        self.assertEqual(ObjectVisit.objects.get().status, VisitStatus.ACTIVE)

    def test_short_occlusion_does_not_end_the_visit(self):
        emb = unit_vector()
        self.poll([self.det(emb=emb)])
        self.poll([self.det(emb=emb)])
        self.poll([])  # a bus drives in front for one poll
        self.poll([self.det(emb=emb)])

        self.assertEqual(self.captures, 1)
        self.assertEqual(ObjectVisit.objects.count(), 1)

    def test_back_in_same_spot_soon_after_exit_continues_the_visit(self):
        emb = unit_vector()
        self.poll([self.det(emb=emb)])
        self.poll([self.det(emb=emb)])
        for _ in range(4):
            self.poll([])
        self.assertEqual(ObjectVisit.objects.get().status, VisitStatus.EXITED)

        self.poll([self.det(emb=emb)])
        self.assertEqual(self.captures, 1)
        self.assertEqual(ObjectVisit.objects.get().status, VisitStatus.ACTIVE)

    def test_object_that_leaves_and_returns_later_gets_a_second_snapshot(self):
        emb = unit_vector()
        self.poll([self.det(emb=emb, track_id=1)])
        self.poll([self.det(emb=emb, track_id=1)])
        for _ in range(4):
            self.poll([])
        self.poll([], advance=15 * 60)  # well past the stationary window
        self.poll([self.det(emb=emb, track_id=2)])
        self.poll([self.det(emb=emb, track_id=2)])

        self.assertEqual(self.captures, 2)
        self.assertEqual(GlobalObject.objects.count(), 1)  # ReID still knows it
        self.assertEqual(ObjectVisit.objects.count(), 2)

    def test_different_car_parked_in_same_spot_is_a_new_object(self):
        first = unit_vector()
        self.poll([self.det(emb=first, track_id=1)])
        self.poll([self.det(emb=first, track_id=1)])
        for _ in range(4):
            self.poll([])
        other = unit_vector()
        self.poll([self.det(emb=other, track_id=2)])
        self.poll([self.det(emb=other, track_id=2)])

        self.assertEqual(self.captures, 2)
        self.assertEqual(GlobalObject.objects.count(), 2)

    def test_detector_flipping_car_and_truck_stays_one_object(self):
        emb = unit_vector()
        for i in range(6):
            self.poll([self.det(emb=emb, cls="car" if i % 2 else "truck")])

        self.assertEqual(self.captures, 1)

    def test_one_frame_flicker_leaves_no_snapshot_or_ghost_object(self):
        self.poll([self.det(emb=unit_vector())])
        for _ in range(4):
            self.poll([])

        self.assertEqual(self.captures, 0)
        self.assertFalse(ObjectVisit.objects.exists())
        self.assertFalse(GlobalObject.objects.exists())

    def test_ml_track_age_confirms_a_passing_object_on_its_only_poll(self):
        self.poll([self.det(emb=unit_vector(), ml_age=2.5)])
        self.assertEqual(self.captures, 1)

    def test_two_people_standing_together_stay_two_visits(self):
        a, b = unit_vector(), unit_vector()
        box_a, box_b = [100, 100, 160, 300], [105, 102, 165, 302]
        for _ in range(3):
            self.poll([
                self.det(cls="person", box=box_a, emb=a),
                self.det(cls="person", box=box_b, emb=b),
            ])

        self.assertEqual(self.captures, 2)
        self.assertEqual(ObjectVisit.objects.filter(status=VisitStatus.ACTIVE).count(), 2)
