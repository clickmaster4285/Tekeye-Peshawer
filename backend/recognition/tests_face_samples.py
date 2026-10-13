"""Gallery scoring, CCTV face-sample review, enrollment pose coverage and threshold calibration."""

import io
import shutil
import tempfile
from pathlib import Path

import numpy as np
from django.core.management import call_command
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from recognition.models import FaceEnrollment, FaceSample
from recognition.services import face_samples, gallery_index
from recognition.services.gallery_index import decide, get_gallery_index, identity_scores, invalidate_gallery
from recognition.views import pose_coverage, pose_hint, _record_pose
from users.models import Staff, User

RNG = np.random.default_rng(7)


def _unit(vec):
    return vec / np.linalg.norm(vec)


def _near(base, sim):
    noise = _unit(RNG.normal(size=base.size))
    noise = _unit(noise - (noise @ base) * base)
    return _unit(sim * base + np.sqrt(1 - sim**2) * noise)


class GalleryScoringTests(TestCase):
    def test_identity_score_is_mean_of_top_three(self):
        hits = [("staff-1", 0.9), ("staff-1", 0.5), ("staff-1", 0.4), ("staff-1", 0.1), ("staff-2", 0.6)]
        scores = identity_scores(hits)
        self.assertAlmostEqual(scores["staff-1"], (0.9 + 0.5 + 0.4) / 3, places=5)
        self.assertAlmostEqual(scores["staff-2"], 0.6, places=5)

    def test_one_stray_vector_no_longer_carries_a_match(self):
        # Old rule (max) would match staff-1 at 0.62; the mean of its top three is below the threshold.
        result = decide(identity_scores([("staff-1", 0.62), ("staff-1", 0.2), ("staff-1", 0.18)]), threshold=0.38)
        self.assertIsNone(result["gallery_key"])
        self.assertEqual(result["best_key"], "staff-1")

    def test_close_runner_up_is_ambiguous(self):
        result = decide({"staff-1": 0.50, "staff-2": 0.47}, threshold=0.38)
        self.assertTrue(result["ambiguous"])
        self.assertIsNone(result["gallery_key"])


@override_settings(ATTENDANCE_INSIGHTFACE_MODEL="buffalo_l")
class FaceSampleTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media)
        self.media_override.enable()
        face_samples._last_unmatched.clear()
        # Worker threads drop their DB connection after saving; inside a test transaction that would end it.
        for name in ("release_db", "close_old_connections"):
            patcher = mock.patch.object(face_samples, name, lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.alice = Staff.objects.create(full_name="Alice")
        self.bob = Staff.objects.create(full_name="Bob")
        self.alice_vec = _unit(RNG.normal(size=512))
        self.bob_vec = _unit(RNG.normal(size=512))
        for staff, vec in ((self.alice, self.alice_vec), (self.bob, self.bob_vec)):
            FaceEnrollment.objects.create(
                staff=staff,
                dataset_folder=f"dataset/staff_{staff.pk}",
                is_trained=True,
                embedding=vec.tolist(),
                embeddings=[_near(vec, 0.9).tolist() for _ in range(4)],
            )
        invalidate_gallery()
        self.crop = np.full((120, 100, 3), 128, dtype=np.uint8)

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        invalidate_gallery()

    def _save(self, kind, key, vec, confidence=0.5):
        face_samples.save_sample(
            kind=kind,
            camera_id=999,
            crop=self.crop,
            embedding=vec,
            suggested_key=key,
            confidence=confidence,
            quality=0.8,
        )

    def test_punch_samples_limited_to_one_per_person_per_day(self):
        self._save(FaceSample.KIND_PUNCH, f"staff-{self.alice.pk}", _near(self.alice_vec, 0.6))
        self._save(FaceSample.KIND_PUNCH, f"staff-{self.alice.pk}", _near(self.alice_vec, 0.6))
        self._save(FaceSample.KIND_PUNCH, f"staff-{self.bob.pk}", _near(self.bob_vec, 0.6))
        self.assertEqual(FaceSample.objects.filter(suggested_staff=self.alice).count(), 1)
        self.assertEqual(FaceSample.objects.count(), 2)
        sample = FaceSample.objects.get(suggested_staff=self.alice)
        self.assertTrue(Path(self.media, sample.image.name).is_file())
        self.assertEqual(len(sample.embedding), 512)

    def test_approved_sample_joins_gallery_and_reject_removes_it(self):
        before = len(get_gallery_index())
        self._save(FaceSample.KIND_UNMATCHED, f"staff-{self.alice.pk}", _near(self.alice_vec, 0.35))
        sample = FaceSample.objects.get()
        self.assertEqual(sample.status, FaceSample.STATUS_PENDING)
        self.assertEqual(len(get_gallery_index()), before)  # pending samples are not used

        face_samples.review_sample(sample, approve=True)
        self.assertEqual(sample.staff, self.alice)
        self.assertEqual(len(get_gallery_index()), before + 1)

        face_samples.review_sample(sample, approve=False)
        self.assertEqual(len(get_gallery_index()), before)

    def test_samples_need_trained_photos_and_matching_model(self):
        carol = Staff.objects.create(full_name="Carol")  # no enrollment
        before = len(get_gallery_index())
        FaceSample.objects.create(
            kind=FaceSample.KIND_PUNCH, status=FaceSample.STATUS_APPROVED, staff=carol,
            embedding=self.alice_vec.tolist(), model_name="buffalo_l", image="x.jpg",
        )
        FaceSample.objects.create(
            kind=FaceSample.KIND_PUNCH, status=FaceSample.STATUS_APPROVED, staff=self.alice,
            embedding=self.alice_vec.tolist(), model_name="antelopev2", image="y.jpg",
        )
        invalidate_gallery()
        self.assertEqual(len(get_gallery_index()), before)

    def test_samples_per_person_are_capped(self):
        before = len(get_gallery_index())
        for _ in range(gallery_index.MAX_SAMPLES_PER_STAFF + 3):
            FaceSample.objects.create(
                kind=FaceSample.KIND_PUNCH, status=FaceSample.STATUS_APPROVED, staff=self.alice,
                embedding=_near(self.alice_vec, 0.6).tolist(), model_name="buffalo_l", image="z.jpg",
            )
        invalidate_gallery()
        self.assertEqual(len(get_gallery_index()), before + gallery_index.MAX_SAMPLES_PER_STAFF)

    def test_review_api_approves_as_another_person(self):
        admin = User.objects.create_user(
            username="hradmin", password="pass12345", email="hr@ciis.test", phone="03000000001",
            role="ADMIN", full_name="HR Admin", location="",
        )
        client = APIClient()
        client.force_authenticate(admin)
        self._save(FaceSample.KIND_UNMATCHED, f"staff-{self.alice.pk}", _near(self.bob_vec, 0.4))
        sample = FaceSample.objects.get()

        listing = client.get("/api/recognition/samples/").json()
        self.assertEqual(listing["pending_count"], 1)
        self.assertEqual(listing["results"][0]["suggested_staff_name"], "Alice")

        response = client.post(
            f"/api/recognition/samples/{sample.pk}/review/",
            {"action": "approve", "staff_id": self.bob.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        sample.refresh_from_db()
        self.assertEqual((sample.status, sample.staff_id, sample.reviewed_by_id), ("approved", self.bob.pk, admin.pk))
        self.assertEqual(client.get("/api/recognition/samples/").json()["pending_count"], 0)

    def test_review_api_requires_hr(self):
        user = User.objects.create_user(
            username="plain", password="pass12345", email="p@ciis.test", phone="03000000002",
            role="VIEWER", full_name="Plain", location="",
        )
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get("/api/recognition/samples/").status_code, 403)

    def test_calibration_recommends_threshold_above_impostors(self):
        for staff, vec in ((self.alice, self.alice_vec), (self.bob, self.bob_vec)):
            for sim in (0.45, 0.5, 0.55, 0.6, 0.65):
                FaceSample.objects.create(
                    kind=FaceSample.KIND_PUNCH, status=FaceSample.STATUS_APPROVED, staff=staff,
                    suggested_staff=staff, embedding=_near(vec, sim).tolist(), model_name="buffalo_l", image="a.jpg",
                )
        # Bob mistaken for Alice: Bob's face scores ~0.3 against Alice.
        impostor = _unit(0.3 * self.alice_vec + 0.9 * self.bob_vec)
        FaceSample.objects.create(
            kind=FaceSample.KIND_UNMATCHED, status=FaceSample.STATUS_REJECTED, suggested_staff=self.alice,
            embedding=impostor.tolist(), model_name="buffalo_l", image="b.jpg",
        )
        out = io.StringIO()
        call_command("calibrate_attendance_threshold", "--min-probes", "5", stdout=out)
        text = out.getvalue()
        self.assertIn("10 genuine probes", text)
        line = next(l for l in text.splitlines() if "ATTENDANCE_CCTV_SIMILARITY_THRESHOLD=" in l)
        recommended = float(line.split("=")[1])
        highest_impostor = float(text.split("Highest impostor score ")[1].split()[0])
        self.assertGreater(recommended, highest_impostor)
        self.assertIn("Alice ↔ Bob", text)


class PoseCoverageTests(TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def _add(self, name, bucket):
        (self.folder / name).write_bytes(b"jpg")
        _record_pose(self.folder, name, bucket)

    def test_hints_walk_through_front_then_both_sides(self):
        self.assertEqual(pose_hint(pose_coverage(self.folder)), "Next: look straight at the camera")
        for i in range(3):
            self._add(f"face_{i}.jpg", "front")
        self.assertIn("one side", pose_hint(pose_coverage(self.folder)))
        self._add("face_3.jpg", "side_b")
        self.assertIn("other side", pose_hint(pose_coverage(self.folder)))
        self._add("face_4.jpg", "side_a")
        self.assertEqual(pose_coverage(self.folder), {"front": 3, "side_a": 1, "side_b": 1})
        self.assertIn("complete", pose_hint(pose_coverage(self.folder)))

    def test_deleted_photos_are_not_counted(self):
        self._add("face_0.jpg", "side_a")
        (self.folder / "face_0.jpg").unlink()
        self.assertEqual(pose_coverage(self.folder)["side_a"], 0)
