"""Identity engine, attendance policy and review loop (synthetic embeddings — no InsightFace)."""

from datetime import datetime, time
from unittest.mock import patch

import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from identity.models import (
    DecisionOutcome,
    FaceGalleryEntry,
    GallerySource,
    IdentityDecision,
    IdentityProfile,
    RecognitionMode,
    ReviewStatus,
)
from identity.services import attendance_policy
from identity.services.engine import PersonIdentityEngine
from identity.services.gallery import INSIGHTFACE_MODEL, add_live_entry, get_gallery_index
from identity.services.quality import FaceQuality
from users.models import Attendance, Staff, User

RNG = np.random.default_rng(7)
DIM = 512


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def near(base, sim):
    """A unit vector with cosine similarity ≈ ``sim`` to ``base``."""
    noise = unit(RNG.normal(size=DIM))
    noise = unit(noise - (noise @ base) * base)
    return unit(sim * base + np.sqrt(1 - sim**2) * noise)


def good_quality(score=0.8):
    return FaceQuality(score=score, det_score=0.9, face_px=120, blur=200, yaw=5, pitch=3, brightness=120)


@override_settings(
    ATTENDANCE_CCTV_SIMILARITY_THRESHOLD=0.38,
    IDENTITY_MIN_MARGIN=0.05,
    IDENTITY_ACCEPT_CONFIDENCE=0.55,
    IDENTITY_UNKNOWN_RECORD_INTERVAL_SEC=0,
    IDENTITY_REVIEW_RECORD_INTERVAL_SEC=0,
)
class IdentityEngineTests(TestCase):
    def setUp(self):
        self.ahmed = Staff.objects.create(full_name="Ahmed", cnic="11111-1111111-1")
        self.ali = Staff.objects.create(full_name="Ali", cnic="22222-2222222-2")
        self.ahmed_face = unit(RNG.normal(size=DIM))
        self.ali_face = unit(RNG.normal(size=DIM))
        for staff, face in ((self.ahmed, self.ahmed_face), (self.ali, self.ali_face)):
            for _ in range(3):
                FaceGalleryEntry.objects.create(
                    staff=staff,
                    model_name=INSIGHTFACE_MODEL,
                    embedding=near(face, 0.85).tolist(),
                    source=GallerySource.ENROLLMENT,
                    quality_score=0.8,
                )
        get_gallery_index().refresh(force=True)
        self.engine = PersonIdentityEngine()

    def test_strong_match_is_accepted_and_explained(self):
        r = self.engine.identify(near(self.ahmed_face, 0.7), quality=good_quality(), source="cctv")
        self.assertEqual(r.outcome, DecisionOutcome.ACCEPTED)
        self.assertEqual(r.staff_id, self.ahmed.pk)
        self.assertGreater(r.factors["margin"], 0.2)
        self.assertIn("margin", r.reason)

    def test_borderline_similarity_goes_to_review(self):
        r = self.engine.identify(near(self.ahmed_face, 0.40), quality=good_quality(), source="cctv")
        self.assertEqual(r.outcome, DecisionOutcome.REVIEW)
        self.assertEqual(r.staff_id, self.ahmed.pk)

    def test_blurry_face_is_not_auto_accepted(self):
        r = self.engine.identify(near(self.ahmed_face, 0.6), quality=good_quality(0.1), source="cctv")
        self.assertEqual(r.outcome, DecisionOutcome.REVIEW)
        self.assertIn("quality", r.reason)

    def test_stranger_is_unknown(self):
        r = self.engine.identify(unit(RNG.normal(size=DIM)), quality=good_quality(), source="cctv")
        self.assertEqual(r.outcome, DecisionOutcome.UNKNOWN)
        self.assertIsNone(r.staff_id)

    def test_track_disagreement_forces_review(self):
        for _ in range(4):
            self.engine.identify(
                near(self.ali_face, 0.7), quality=good_quality(), source="cctv", camera_id=1, track_id=9
            )
        r = self.engine.identify(
            near(self.ahmed_face, 0.7), quality=good_quality(), source="cctv", camera_id=1, track_id=9
        )
        self.assertEqual(r.outcome, DecisionOutcome.REVIEW)
        self.assertIn("track", r.reason)

    # ── attendance policy ────────────────────────────────────────────────

    def _accepted(self):
        return self.engine.identify(near(self.ahmed_face, 0.7), quality=good_quality(), source="cctv")

    def test_automatic_mode_marks_attendance(self):
        IdentityProfile.objects.create(staff=self.ahmed, recognition_mode=RecognitionMode.AUTOMATIC)
        out = attendance_policy.apply(self._accepted(), staff=self.ahmed, camera=None, source="cctv")
        self.assertEqual(out["attendance_action"], "check_in")
        self.assertEqual(Attendance.objects.filter(staff=self.ahmed).count(), 1)
        self.assertEqual(out["decision"].attendance_id, out["record"].pk)

    def test_manual_mode_never_marks(self):
        IdentityProfile.objects.create(staff=self.ahmed, recognition_mode=RecognitionMode.MANUAL)
        out = attendance_policy.apply(self._accepted(), staff=self.ahmed, camera=None, source="cctv")
        self.assertEqual(out["action"], "manual_mode")
        self.assertFalse(Attendance.objects.exists())

    def test_assisted_mode_queues_one_checkin_then_approval_marks_and_learns(self):
        IdentityProfile.objects.create(staff=self.ahmed, recognition_mode=RecognitionMode.ASSISTED)
        out = attendance_policy.apply(self._accepted(), staff=self.ahmed, camera=None, source="cctv")
        self.assertEqual(out["action"], "assisted_pending")
        self.assertFalse(Attendance.objects.exists())
        decision = out["decision"]
        self.assertEqual(decision.review_status, ReviewStatus.PENDING)
        self.assertTrue(decision.probe_embedding)

        again = attendance_policy.apply(self._accepted(), staff=self.ahmed, camera=None, source="cctv")
        self.assertEqual(again["action"], "pending_exists")
        self.assertIsNone(again["decision"])

        admin = User.objects.create_user(username="hr", password="x")
        before = FaceGalleryEntry.objects.filter(staff=self.ahmed, is_active=True).count()
        # quality 0.8 ≥ gallery minimum; probe is not a near-duplicate of 0.85-similar entries
        result = attendance_policy.approve_decision(decision, user=admin)
        self.assertEqual(result["attendance"]["action"], "check_in")
        self.assertTrue(result["gallery"]["added"], result["gallery"])
        self.assertEqual(FaceGalleryEntry.objects.filter(staff=self.ahmed, is_active=True).count(), before + 1)
        self.assertEqual(IdentityProfile.objects.get(staff=self.ahmed).confirmed_matches, 1)

        # Check-in approved → later sightings update last-seen automatically.
        later = attendance_policy.apply(
            self._accepted(),
            staff=self.ahmed,
            camera=None,
            source="cctv",
            now=timezone.now() + timezone.timedelta(minutes=10),
        )
        self.assertEqual(later["attendance_action"], "check_out")

    def test_correcting_identity_counts_against_original_candidate(self):
        IdentityProfile.objects.create(staff=self.ahmed, recognition_mode=RecognitionMode.AUTOMATIC)
        r = self.engine.identify(near(self.ahmed_face, 0.40), quality=good_quality(), source="cctv")
        out = attendance_policy.apply(r, staff=self.ahmed, camera=None, source="cctv")
        self.assertEqual(out["action"], "identity_review")
        admin = User.objects.create_user(username="hr2", password="x")
        attendance_policy.approve_decision(out["decision"], user=admin, staff=self.ali, add_to_gallery=False)
        self.assertEqual(IdentityProfile.objects.get(staff=self.ahmed).rejected_matches, 1)
        self.assertEqual(IdentityProfile.objects.get(staff=self.ali).confirmed_matches, 1)
        self.assertTrue(Attendance.objects.filter(staff=self.ali).exists())

    def test_outside_shift_goes_to_review(self):
        self.ahmed.work_shift_start = time(9, 0)
        self.ahmed.work_shift_end = time(17, 0)
        self.ahmed.save()
        IdentityProfile.objects.create(staff=self.ahmed, recognition_mode=RecognitionMode.AUTOMATIC)
        at_3am = timezone.make_aware(datetime(2026, 9, 26, 3, 0))
        out = attendance_policy.apply(self._accepted(), staff=self.ahmed, camera=None, source="cctv", now=at_3am)
        self.assertEqual(out["action"], "outside_shift")
        self.assertFalse(Attendance.objects.exists())

    # ── gallery hygiene ──────────────────────────────────────────────────

    def test_near_duplicate_and_low_quality_faces_are_not_added(self):
        existing = FaceGalleryEntry.objects.filter(staff=self.ahmed).first()
        entry, msg = add_live_entry(staff=self.ahmed, embedding=existing.embedding, quality={"score": 0.9})
        self.assertIsNone(entry)
        self.assertIn("duplicate", msg.lower())
        entry, msg = add_live_entry(staff=self.ahmed, embedding=near(self.ahmed_face, 0.6), quality={"score": 0.2})
        self.assertIsNone(entry)
        self.assertIn("quality", msg.lower())


class IdentityApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="hr-admin", password="x", role="HR")
        self.client.force_authenticate(self.user)
        self.staff = Staff.objects.create(full_name="Usman", cnic="33333-3333333-3")

    def test_mode_switch_and_readiness(self):
        res = self.client.post(f"/api/identity/staff/{self.staff.pk}/mode/", {"recognition_mode": "automatic"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["recognition_mode"], "automatic")
        self.assertFalse(res.data["automatic_readiness"]["ready"])

    def test_reject_decision(self):
        d = IdentityDecision.objects.create(
            source="cctv",
            staff=self.staff,
            outcome=DecisionOutcome.REVIEW,
            review_status=ReviewStatus.PENDING,
        )
        res = self.client.post(f"/api/identity/decisions/{d.pk}/reject/", {"note": "not him"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["review_status"], "rejected")
        res = self.client.get("/api/identity/decisions/?review_status=pending")
        self.assertEqual(res.data["count"], 0)


@override_settings(IDENTITY_SFACE_ACCEPT_SIMILARITY=0.36, IDENTITY_SFACE_REVIEW_BAND=0.06)
class JourneyIdentityTests(TestCase):
    """SFace (128-d) journey faces go through the same engine and review loop."""

    def setUp(self):
        from types import SimpleNamespace

        from identity.services.gallery import SFACE_MODEL

        self.sface = SFACE_MODEL
        self.staff = Staff.objects.create(full_name="Bilal", cnic="44444-4444444-4")
        self.other = Staff.objects.create(full_name="Hamza", cnic="55555-5555555-5")
        self.face = unit(RNG.normal(size=128))
        other_face = unit(RNG.normal(size=128))
        for staff, face in ((self.staff, self.face), (self.other, other_face)):
            for _ in range(3):
                noise = unit(RNG.normal(size=128))
                FaceGalleryEntry.objects.create(
                    staff=staff,
                    model_name=SFACE_MODEL,
                    embedding=unit(0.9 * face + 0.44 * noise).tolist(),
                    source=GallerySource.ENROLLMENT,
                    quality_score=None,
                )
        get_gallery_index(SFACE_MODEL).refresh(force=True)
        self.camera = SimpleNamespace(pk=77)

    def _probe(self, sim):
        noise = unit(RNG.normal(size=128))
        noise = unit(noise - (noise @ self.face) * self.face)
        return unit(sim * self.face + np.sqrt(1 - sim**2) * noise).tolist()

    def test_confident_sface_match_names_the_journey(self):
        from identity.services.journey import identify_journey_face

        ident = identify_journey_face(face_embedding=self._probe(0.8), face_label="", camera=self.camera, track_id=5)
        self.assertEqual(ident.staff_id, self.staff.pk)
        self.assertEqual(ident.result.model_name, self.sface)
        self.assertIsNone(ident.result.factors["quality"])  # SFace has no quality score — not guessed

    def test_ml_label_alone_does_not_name_a_person(self):
        from identity.services.journey import identify_journey_face

        stranger = unit(RNG.normal(size=128)).tolist()
        ident = identify_journey_face(face_embedding=stranger, face_label="Bilal", camera=self.camera, track_id=6)
        self.assertIsNone(ident.staff_id)
        self.assertEqual(ident.result.factors["ml_label"], "Bilal")

    def test_wrong_size_embedding_falls_back_to_label(self):
        from identity.services.journey import identify_journey_face

        self.assertIsNone(identify_journey_face(face_embedding=[0.1] * 512, face_label="x", camera=self.camera, track_id=1))

    @patch("identity.services.gallery.push_sface_gallery_to_ml_async")
    def test_review_is_recorded_once_per_track_and_approval_merges_journey(self, push_mock):
        from identity.services.journey import identify_journey_face
        from person_journey.models import JourneyEvent, JourneyPerson, PersonStatus, PersonType
        from person_journey.services import create_journey_person, register_staff_journey_person

        staff_person = register_staff_journey_person(self.staff)
        unknown = create_journey_person(person_type=PersonType.UNKNOWN, display_name="Unknown")
        JourneyEvent.objects.create(journey_person=unknown, event_type="camera_detection", title="seen")

        first = identify_journey_face(face_embedding=self._probe(0.33), face_label="", camera=self.camera, track_id=9)
        self.assertEqual(first.result.outcome, DecisionOutcome.REVIEW)
        decision = first.record(camera=None, journey_person=unknown)
        self.assertEqual(decision.review_status, ReviewStatus.PENDING)
        again = identify_journey_face(face_embedding=self._probe(0.33), face_label="", camera=self.camera, track_id=9)
        self.assertIsNone(again.record(camera=None, journey_person=unknown))

        admin = User.objects.create_user(username="hr3", password="x")
        out = attendance_policy.approve_decision(decision, user=admin)
        self.assertIsNone(out["attendance"])  # journey sightings don't mark attendance by default
        self.assertEqual(out["journey"]["person_code"], staff_person.code)
        unknown.refresh_from_db()
        self.assertEqual(unknown.status, PersonStatus.MERGED)
        self.assertEqual(unknown.merged_into_id, staff_person.pk)
        self.assertTrue(JourneyEvent.objects.filter(journey_person=staff_person, title="seen").exists())
        self.assertTrue(out["gallery"]["added"], out["gallery"])
        self.assertTrue(
            FaceGalleryEntry.objects.filter(staff=self.staff, model_name=self.sface, source="approved_live").exists()
        )
        push_mock.assert_called_once()  # ML service's SFace gallery gets the new face
        self.assertEqual(JourneyPerson.objects.filter(staff=self.staff, status=PersonStatus.ACTIVE).count(), 1)
