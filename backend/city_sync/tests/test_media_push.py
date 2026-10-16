"""City -> HQ image upload: newest first, several at once, results recorded."""

from __future__ import annotations

import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from city_sync.media_sync import push_media_once
from city_sync.models import MediaQueue
from city_sync.tests.test_sites import CITY


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.content = b"{}"
        self.text = ""

    def json(self):
        return self._data


@override_settings(**CITY, SYNC_MEDIA_PARALLEL=4)
class MediaPushTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

    def queue(self, name: str, minutes_ago: int, priority=MediaQueue.PRIORITY_ROUTINE) -> MediaQueue:
        (Path(self.tmp.name) / name).write_bytes(b"jpg-bytes")
        row = MediaQueue.objects.create(
            location_code="ABBOTTABAD", path=name, sha256="x", size_bytes=9, priority=priority
        )
        MediaQueue.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return row

    def fake_hq(self, sent: list):
        """HQ that accepts everything and records the order files were started in."""
        lock = threading.Lock()

        def post(url, json=None, **_kw):
            if url.endswith("/media/init"):
                with lock:
                    sent.append(json["source_path"])
                return _Resp(data={"offset": 0})
            return _Resp(data={"verified": True})

        def put(url, **_kw):
            return _Resp()

        return post, put

    def test_newest_images_go_first(self):
        self.queue("old.jpg", minutes_ago=600)
        self.queue("new.jpg", minutes_ago=1)
        self.queue("mid.jpg", minutes_ago=60)
        sent: list = []
        post, put = self.fake_hq(sent)
        with mock.patch("city_sync.media_sync.requests.post", side_effect=post), mock.patch(
            "city_sync.media_sync.requests.put", side_effect=put
        ):
            stats = push_media_once(limit=1)
        self.assertEqual(sent, ["new.jpg"])
        self.assertEqual(stats["verified"], 1)

    def test_evidence_priority_still_beats_newer_routine_images(self):
        self.queue("routine-new.jpg", minutes_ago=1)
        self.queue("evidence-old.jpg", minutes_ago=600, priority=MediaQueue.PRIORITY_EVIDENCE)
        sent: list = []
        post, put = self.fake_hq(sent)
        with mock.patch("city_sync.media_sync.requests.post", side_effect=post), mock.patch(
            "city_sync.media_sync.requests.put", side_effect=put
        ):
            push_media_once(limit=1)
        self.assertEqual(sent, ["evidence-old.jpg"])

    def test_batch_uploads_all_and_records_each_result(self):
        rows = [self.queue(f"img{i}.jpg", minutes_ago=i) for i in range(6)]

        def post(url, json=None, **_kw):
            if url.endswith("/media/init"):
                if json["source_path"] == "img2.jpg":
                    return _Resp(500)
                return _Resp(data={"offset": 0})
            return _Resp(data={"verified": True})

        with mock.patch("city_sync.media_sync.requests.post", side_effect=post), mock.patch(
            "city_sync.media_sync.requests.put", return_value=_Resp()
        ):
            stats = push_media_once(limit=10)
        self.assertEqual((stats["attempted"], stats["verified"]), (6, 5))
        statuses = {r.path: MediaQueue.objects.get(pk=r.pk) for r in rows}
        self.assertEqual(statuses["img2.jpg"].status, MediaQueue.STATUS_PENDING)
        self.assertEqual(statuses["img2.jpg"].attempts, 1)
        self.assertIn("init HTTP 500", statuses["img2.jpg"].last_error)
        self.assertEqual(statuses["img0.jpg"].status, MediaQueue.STATUS_VERIFIED)
        self.assertEqual(statuses["img0.jpg"].bytes_uploaded, 9)
