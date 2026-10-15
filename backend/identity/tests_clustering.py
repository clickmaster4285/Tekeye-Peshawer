"""Unknown-person observations, clustering and cluster review (synthetic SFace vectors)."""

from datetime import timedelta
from unittest.mock import patch

import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone

from identity.models import (
    ClusterStatus,
    FaceGalleryEntry,
    GallerySource,
    IdentityDecision,
    PersonObservation,
    ReviewStatus,
    UnknownCluster,
)
from identity.services import observations
from identity.services.attendance_policy import approve_decision, reject_decision
from identity.services.clustering import run_unknown_clustering
from identity.services.gallery import SFACE_MODEL, get_gallery_index
from person_journey.models import JourneyPerson, PersonStatus, PersonType
from person_journey.services import create_journey_person
from users.models import Staff, User

RNG = np.random.default_rng(11)


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def near(base, sim):
    noise = unit(RNG.normal(size=base.shape[0]))
    noise = unit(noise - (noise @ base) * base)
    return unit(sim * base + np.sqrt(1 - sim**2) * noise)


def unknown():
    return create_journey_person(person_type=PersonType.UNKNOWN, display_name="Unknown")


def add_obs(person, face, *, minutes_ago=0, camera=None, track=1):
    obs = PersonObservation.objects.create(
        journey_person=person, camera=camera, track_id=track, face_embedding=face.tolist()
    )
    PersonObservation.objects.filter(pk=obs.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return obs


@override_settings(IDENTITY_OBS_MIN_INTERVAL_SEC=20, IDENTITY_OBS_MAX_PER_PERSON=3)
class ObservationFilterTests(TestCase):
    def setUp(self):
        observations._last.clear()
        observations._counts.clear()
        self.person = unknown()
        self.face = unit(RNG.normal(size=128))

    def test_standing_still_is_one_observation(self):
        first = observations.record_observation(person=self.person, camera=None, track_id=1, face_embedding=self.face)
        self.assertIsNotNone(first)
        for _ in range(30):
            observations.record_observation(person=self.person, camera=None, track_id=1, face_embedding=self.face)
        self.assertEqual(PersonObservation.objects.filter(journey_person=self.person).count(), 1)

    def test_cap_per_person(self):
        with patch("identity.services.observations.time.monotonic") as clock:
            for i in range(10):
                clock.return_value = 1000 + i * 60
                observations.record_observation(
                    person=self.person, camera=None, track_id=1, face_embedding=near(self.face, 0.6)
                )
        self.assertEqual(PersonObservation.objects.filter(journey_person=self.person).count(), 3)


@override_settings(
    IDENTITY_CLUSTER_FACE_SIM=0.48,
    IDENTITY_CLUSTER_MIN_OBS=2,
    IDENTITY_CLUSTER_MIN_OBS_FOR_CANDIDATE=4,
    IDENTITY_SFACE_ACCEPT_SIMILARITY=0.36,
    IDENTITY_CLUSTER_GALLERY_ADD=3,
)
class ClusteringTests(TestCase):
    def setUp(self):
        self.stranger = unit(RNG.normal(size=128))
        self.other_stranger = unit(RNG.normal(size=128))

    def test_same_face_across_u_codes_becomes_one_cluster(self):
        a, b, c = unknown(), unknown(), unknown()
        for p, mins in ((a, 300), (b, 120), (c, 5)):
            add_obs(p, near(self.stranger, 0.8), minutes_ago=mins)
            add_obs(p, near(self.stranger, 0.8), minutes_ago=mins - 1)
        d = unknown()
        add_obs(d, near(self.other_stranger, 0.8))
        add_obs(d, near(self.other_stranger, 0.8), minutes_ago=2)

        stats = run_unknown_clustering()
        self.assertEqual(stats["multi_person_clusters"], 1)
        codes = {m.cluster.code for m in (a.unknown_cluster_membership, b.unknown_cluster_membership)}
        self.assertEqual(len(codes), 1)
        a.refresh_from_db()
        d.refresh_from_db()
        self.assertEqual(a.unknown_cluster_membership.cluster.person_count, 3)
        self.assertNotEqual(d.unknown_cluster_membership.cluster_id, a.unknown_cluster_membership.cluster_id)

        # Re-running is stable: same cluster ids, no duplicates.
        first_ids = set(UnknownCluster.objects.values_list("id", flat=True))
        run_unknown_clustering()
        self.assertEqual(set(UnknownCluster.objects.values_list("id", flat=True)), first_ids)

    def test_two_people_side_by_side_are_never_linked(self):
        """Look-alikes on the same camera at the same moment, different tracks → two people."""
        from identity.services.clustering import _centroid, _components, _Obs, _Person

        now = timezone.now()

        def person(pid, track, cam, offset_s):
            faces = [near(self.stranger, 0.9) for _ in range(2)]
            p = _Person(pid, [_Obs(now + timedelta(seconds=offset_s), cam, track, f, None, pid * 10 + i, "") for i, f in enumerate(faces)])
            p.face = _centroid(faces)
            return p

        together = {1: person(1, 1, 5, 0), 2: person(2, 2, 5, 1)}
        self.assertEqual(sorted(map(sorted, _components(together))), [[1], [2]])
        apart = {1: person(1, 1, 5, 0), 2: person(2, 2, 6, 1)}  # different cameras → can be one person
        self.assertEqual(_components(apart), [[1, 2]])

    @patch("identity.services.gallery.push_sface_gallery_to_ml_async")
    def test_candidate_employee_then_approval_merges_all_journeys_and_learns(self, _push):
        staff = Staff.objects.create(full_name="Tariq", cnic="66666-6666666-6")
        employee_face = unit(RNG.normal(size=128))
        for _ in range(3):
            FaceGalleryEntry.objects.create(
                staff=staff,
                model_name=SFACE_MODEL,
                embedding=near(employee_face, 0.85).tolist(),
                source=GallerySource.ENROLLMENT,
            )
        get_gallery_index(SFACE_MODEL).refresh(force=True)
        u1, u2 = unknown(), unknown()
        for p in (u1, u2):
            for m in range(3):
                add_obs(p, near(employee_face, 0.75), minutes_ago=m * 10 + (0 if p is u1 else 200))

        stats = run_unknown_clustering()
        self.assertEqual(stats["candidates_suggested"], 1)
        cluster = UnknownCluster.objects.get()
        decision = cluster.candidate_decision
        self.assertEqual(decision.staff_id, staff.pk)
        self.assertEqual(decision.review_status, ReviewStatus.PENDING)
        self.assertEqual(decision.factors["cluster"]["observations"], 6)

        # Waiting for review → not suggested twice.
        self.assertEqual(run_unknown_clustering()["candidates_suggested"], 0)

        reviewer = User.objects.create_user(username="hr-c", password="x")
        out = approve_decision(decision, user=reviewer)
        self.assertIsNone(out["attendance"])
        self.assertEqual(sorted(out["journey"]["merged_persons"]), sorted([u1.code, u2.code]))
        self.assertEqual(out["journey"]["gallery_added"], 3)
        cluster.refresh_from_db()
        self.assertEqual(cluster.status, ClusterStatus.IDENTIFIED)
        self.assertEqual(
            JourneyPerson.objects.filter(staff=staff, status=PersonStatus.ACTIVE).count(), 1
        )
        self.assertEqual(
            FaceGalleryEntry.objects.filter(staff=staff, source=GallerySource.APPROVED_LIVE).count(), 3
        )

    def test_rejected_employee_is_not_suggested_again(self):
        staff = Staff.objects.create(full_name="Waqas", cnic="77777-7777777-7")
        face = unit(RNG.normal(size=128))
        FaceGalleryEntry.objects.create(
            staff=staff, model_name=SFACE_MODEL, embedding=face.tolist(), source=GallerySource.ENROLLMENT
        )
        get_gallery_index(SFACE_MODEL).refresh(force=True)
        u = unknown()
        for m in range(5):
            add_obs(u, near(face, 0.7), minutes_ago=m * 5)
        run_unknown_clustering()
        cluster = UnknownCluster.objects.get()
        reject_decision(cluster.candidate_decision, user=User.objects.create_user(username="hr-r", password="x"))
        cluster.refresh_from_db()
        self.assertEqual(cluster.rejected_staff_ids, [staff.pk])
        self.assertEqual(run_unknown_clustering()["candidates_suggested"], 0)
        self.assertEqual(IdentityDecision.objects.filter(source="cluster").count(), 1)
