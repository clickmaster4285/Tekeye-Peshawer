"""Motion clips collected from ML: storing, linking movements to objects, API, retention, video seeking."""

import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token

from cameras.models import Camera, Nvr, Site
from object_tracking.models import (
    GlobalObject,
    MotionClip,
    ObjectCameraTrack,
    ObjectMovement,
    ObjectVisit,
)
from object_tracking.motion_clips import describe_move, prune_old_clips, pull_from_node, store_clip
from users.models import User

FROM = [100, 100, 200, 200]
TO = [500, 100, 600, 200]


class MotionClipTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="motion-media-")
        self.media_override = self.settings(MEDIA_ROOT=self.media)
        self.media_override.enable()
        nvr = Nvr.objects.create(site=Site.objects.create(code="T", name="T"), name="N", ip_address="127.0.0.1")
        self.camera = Camera.objects.create(nvr=nvr, name="Gate", code="gate", channel=1)
        self.other_camera = Camera.objects.create(nvr=nvr, name="Yard", code="yard", channel=2)
        self.now = timezone.now()

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def meta(self, *, clip_id="cam-1-1-abc", camera=None, movements=None, age=timedelta(0)):
        t = (self.now - age).timestamp()
        return {
            "clip_id": clip_id,
            "camera_key": f"cam-{(camera or self.camera).pk}",
            "part": 1,
            "started_at": t - 12,
            "ended_at": t,
            "duration_sec": 12.0,
            "fps": 6.0,
            "clip_width": 1280,
            "clip_height": 720,
            "source_width": 1280,
            "source_height": 720,
            "movements": movements
            if movements is not None
            else [self.move()],
        }

    def move(self, **kw):
        t = self.now.timestamp()
        mv = {
            "track_id": 42,
            "global_object_id": "GV9",
            "class_name": "car",
            "started_at": t - 7,
            "ended_at": t - 2,
            "still_moving": False,
            "from_bbox": FROM,
            "to_bbox": TO,
        }
        mv.update(kw)
        return mv

    def object_with_visit(self, *, code="GV100", camera=None, bbox=FROM, cls="car"):
        obj = GlobalObject.objects.create(code=code, object_type="vehicle", class_name=cls)
        visit = ObjectVisit.objects.create(
            global_object=obj,
            camera=camera or self.camera,
            entry_at=self.now - timedelta(minutes=10),
            last_seen_at=self.now,
            bbox=bbox,
        )
        return obj, visit


class DescribeMoveTests(TestCase):
    def test_directions(self):
        self.assertEqual(describe_move(FROM, TO, 1280, 720)[2], "right")
        self.assertEqual(describe_move(TO, FROM, 1280, 720)[2], "left")
        self.assertEqual(describe_move(FROM, [100, 400, 200, 500], 1280, 720)[2], "down")
        self.assertEqual(describe_move(FROM, [400, -200, 500, -100], 1280, 720)[2], "up-right")

    def test_distance_and_percent(self):
        dist, pct, _ = describe_move(FROM, TO, 1280, 720)
        self.assertEqual(dist, 400.0)
        self.assertAlmostEqual(pct, 27.2, places=1)

    def test_growing_in_place_is_closer(self):
        self.assertEqual(describe_move(FROM, [80, 80, 220, 220], 1280, 720)[2], "closer")
        self.assertEqual(describe_move([80, 80, 220, 220], FROM, 1280, 720)[2], "farther")


class StoreClipTests(MotionClipTestBase):
    def test_links_movement_by_track_id(self):
        obj, visit = self.object_with_visit()
        ObjectCameraTrack.objects.create(
            global_object=obj, camera=self.camera, local_track_id=42, started_at=self.now - timedelta(minutes=5)
        )
        clip = store_clip(self.meta(), b"video", b"poster", b"end")
        self.assertIsNotNone(clip)
        self.assertEqual(clip.camera, self.camera)
        self.assertTrue(clip.video.name.endswith(".mp4"))
        self.assertTrue(clip.end_frame.name.endswith(".end.jpg"))
        mv = clip.movements.get()
        self.assertEqual((mv.global_object, mv.visit), (obj, visit))
        self.assertEqual((mv.direction, mv.distance_px), ("right", 400.0))
        self.assertAlmostEqual(mv.duration_seconds, 5.0, places=1)

    def test_links_by_resting_spot_when_track_unknown(self):
        obj, visit = self.object_with_visit(bbox=[105, 100, 205, 200])
        clip = store_clip(self.meta(movements=[self.move(track_id=7, global_object_id="")]), b"v", None)
        self.assertEqual(clip.movements.get().global_object, obj)
        self.assertEqual(clip.movements.get().visit, visit)

    def test_spot_match_needs_same_class_group_and_camera(self):
        self.object_with_visit(code="GP1", cls="person")
        self.object_with_visit(code="GV2", camera=self.other_camera)
        clip = store_clip(self.meta(movements=[self.move(track_id=7, global_object_id="")]), b"v", None)
        self.assertIsNone(clip.movements.get().global_object)

    def test_ml_code_only_used_if_object_was_on_this_camera(self):
        # Same code from before an ML restart, seen elsewhere → not linked
        self.object_with_visit(code="GV9", camera=self.other_camera, bbox=[0, 0, 10, 10])
        clip = store_clip(self.meta(movements=[self.move(track_id=7)]), b"v", None)
        self.assertIsNone(clip.movements.get().global_object)
        obj, _ = self.object_with_visit(code="GV10", bbox=[0, 0, 10, 10])
        clip = store_clip(
            self.meta(clip_id="cam-1-2-x", movements=[self.move(track_id=7, global_object_id="GV10")]), b"v", None
        )
        self.assertEqual(clip.movements.get().global_object, obj)

    def test_same_clip_is_stored_once(self):
        self.assertIsNotNone(store_clip(self.meta(), b"v", None))
        self.assertIsNone(store_clip(self.meta(), b"v", None))
        self.assertEqual(MotionClip.objects.count(), 1)

    def test_unknown_camera_key_still_stores_clip(self):
        meta = self.meta()
        meta["camera_key"] = "lobby"
        clip = store_clip(meta, b"v", None)
        self.assertIsNone(clip.camera)
        self.assertIsNone(clip.movements.get().global_object)

    def test_prune_deletes_rows_and_files(self):
        old = store_clip(self.meta(clip_id="old", age=timedelta(days=20)), b"v", b"p", b"e")
        store_clip(self.meta(clip_id="new"), b"v", None)
        path = os.path.join(self.media, old.video.name)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(prune_old_clips(days=14), 1)
        self.assertFalse(os.path.isfile(path))
        self.assertEqual(list(MotionClip.objects.values_list("ml_clip_id", flat=True)), ["new"])
        self.assertEqual(prune_old_clips(days=0), 0)


class FakeResponse:
    def __init__(self, status=200, content=b"", data=None):
        self.status_code, self.content, self._data = status, content, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class PullTests(MotionClipTestBase):
    def test_pull_stores_then_deletes_on_ml(self):
        meta = self.meta()
        deleted = []

        def get(url, **_):
            if url.endswith("/live/motion/clips"):
                return FakeResponse(data={"clips": [meta]})
            return FakeResponse(content=b"mp4" if url.endswith("/video") else b"jpg")

        with patch("requests.get", side_effect=get), patch(
            "requests.delete", side_effect=lambda url, **_: deleted.append(url) or FakeResponse()
        ):
            self.assertEqual(pull_from_node("http://ml:8100/"), 1)
            # Already stored: not stored again, but the ML copy is still removed
            self.assertEqual(pull_from_node("http://ml:8100"), 0)
        self.assertEqual(deleted, [f"http://ml:8100/live/motion/clips/{meta['clip_id']}"] * 2)
        clip = MotionClip.objects.get()
        self.assertTrue(clip.poster and clip.end_frame)

    def test_failed_video_download_keeps_clip_on_ml(self):
        meta = self.meta()

        def get(url, **_):
            if url.endswith("/live/motion/clips"):
                return FakeResponse(data={"clips": [meta]})
            return FakeResponse(status=500)

        with patch("requests.get", side_effect=get), patch("requests.delete") as delete:
            self.assertEqual(pull_from_node("http://ml:8100"), 0)
        delete.assert_not_called()
        self.assertFalse(MotionClip.objects.exists())


class MotionClipApiTests(MotionClipTestBase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(
            username="clips", password="pass12345", email="c@example.com", role="ADMIN", phone="03000000001"
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Token {Token.objects.create(user=user).key}"}
        self.car, _ = self.object_with_visit(code="GV1")
        ObjectCameraTrack.objects.create(
            global_object=self.car, camera=self.camera, local_track_id=42, started_at=self.now - timedelta(minutes=5)
        )
        store_clip(self.meta(clip_id="car"), b"0123456789" * 100, b"p", b"e")
        store_clip(
            self.meta(
                clip_id="person",
                camera=self.other_camera,
                movements=[self.move(track_id=9, global_object_id="GP3", class_name="person")],
                age=timedelta(days=2),
            ),
            b"v",
            None,
        )

    def get(self, **params):
        res = self.client.get("/api/object-tracking/motion-clips/", params, **self.auth)
        self.assertEqual(res.status_code, 200)
        return [r["movements"][0]["ml_object_id"] for r in res.json()["results"]]

    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/object-tracking/motion-clips/").status_code, 401)

    def test_list_and_filters(self):
        self.assertEqual(self.get(), ["GV9", "GP3"])
        self.assertEqual(self.get(camera=self.other_camera.pk), ["GP3"])
        self.assertEqual(self.get(object_type="person"), ["GP3"])  # unlinked: matched by class
        self.assertEqual(self.get(object_type="vehicle"), ["GV9"])
        self.assertEqual(self.get(q="GV1"), ["GV9"])  # backend object code
        self.assertEqual(self.get(q="Yard"), ["GP3"])
        self.assertEqual(self.get(date_from=self.now.date().isoformat()), ["GV9"])
        self.assertEqual(self.get(date_from="not-a-date"), ["GV9", "GP3"])
        self.assertEqual(self.get(object=str(self.car.uuid)), ["GV9"])

    def test_clip_fields(self):
        res = self.client.get("/api/object-tracking/motion-clips/", **self.auth).json()["results"][0]
        self.assertTrue(res["video_url"].endswith(".mp4"))
        self.assertTrue(res["poster_url"] and res["end_frame_url"])
        mv = res["movements"][0]
        self.assertEqual((mv["global_code"], mv["direction"]), ("GV1", "right"))

    def test_object_detail_lists_movements_with_clip(self):
        res = self.client.get(f"/api/object-tracking/objects/{self.car.uuid}/", **self.auth).json()
        self.assertEqual(len(res["movements"]), 1)
        self.assertTrue(res["movements"][0]["clip_detail"]["video_url"].endswith(".mp4"))

    def test_video_supports_range_requests(self):
        clip = MotionClip.objects.get(ml_clip_id="car")
        url = "/media/" + clip.video.name
        full = self.client.get(url, **self.auth)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full["Accept-Ranges"], "bytes")
        part = self.client.get(url, HTTP_RANGE="bytes=10-19", **self.auth)
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part["Content-Range"], "bytes 10-19/1000")
        self.assertEqual(b"".join(part.streaming_content), b"0123456789")
        tail = self.client.get(url, HTTP_RANGE="bytes=-5", **self.auth)
        self.assertEqual(b"".join(tail.streaming_content), b"56789")
        self.assertEqual(self.client.get(url, HTTP_RANGE="bytes=5000-", **self.auth).status_code, 416)
        self.assertEqual(self.client.get(url, HTTP_RANGE="bytes=0-1").status_code, 401)
