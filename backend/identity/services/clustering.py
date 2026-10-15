"""Unknown-person clustering — "same stranger, different U-codes".

    Camera 1 Track 101 ─┐
    Camera 3 Track 55  ─┼─► same person? ─► UnknownCluster UP-0001 ─► candidate employee? ─► you approve
    Camera 7 Track 802 ─┘

Linking rules (per pair of unknown journey persons):
  • face centroids (SFace, averaged over their observations) ≥ IDENTITY_CLUSTER_FACE_SIM, or
  • no face on one side: ReID ≥ IDENTITY_CLUSTER_REID_SIM, same day, within an hour
    (clothing changes across days, so ReID alone never links distant sightings)
  • never linked if both were on the same camera at the same moment as different
    tracks — two people side by side are two people.

Candidates are always *suggestions*: an accepted cluster still waits for a human.
Approval merges every member journey into the employee's journey and adds a
handful of the most varied observations to their gallery.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from identity.models import (
    ClusterStatus,
    DecisionOutcome,
    IdentityDecision,
    PersonObservation,
    ReviewStatus,
    UnknownCluster,
    UnknownClusterMember,
)

logger = logging.getLogger(__name__)


def _f(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def _unit(v) -> np.ndarray | None:
    if v is None or len(v) == 0:
        return None
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a / n if n > 0 else None


@dataclass
class _Obs:
    at: datetime
    camera_id: int | None
    track_id: int | None
    face: np.ndarray | None
    reid: np.ndarray | None
    obs_id: int
    snapshot_path: str


@dataclass
class _Person:
    person_id: int
    obs: list[_Obs] = field(default_factory=list)
    face: np.ndarray | None = None
    reid: np.ndarray | None = None

    @property
    def first(self) -> datetime:
        return min(o.at for o in self.obs)

    @property
    def last(self) -> datetime:
        return max(o.at for o in self.obs)


def _centroid(vectors: list[np.ndarray]) -> np.ndarray | None:
    vecs = [v for v in vectors if v is not None]
    if not vecs:
        return None
    return _unit(np.mean(np.stack(vecs), axis=0))


def _load_people() -> dict[int, _Person]:
    from person_journey.models import PersonStatus, PersonType

    since = timezone.now() - timedelta(days=_f("IDENTITY_CLUSTER_LOOKBACK_DAYS", 7))
    min_obs = int(_f("IDENTITY_CLUSTER_MIN_OBS", 2))
    rows = (
        PersonObservation.objects.filter(
            journey_person__person_type=PersonType.UNKNOWN,
            journey_person__status=PersonStatus.ACTIVE,
            created_at__gte=since,
        )
        .exclude(
            journey_person__unknown_cluster_membership__cluster__status__in=[
                ClusterStatus.IDENTIFIED,
                ClusterStatus.DISMISSED,
            ]
        )
        .values_list(
            "id", "journey_person_id", "created_at", "camera_id", "track_id", "face_embedding", "reid_embedding",
            "snapshot_path",
        )
    )
    people: dict[int, _Person] = {}
    for obs_id, pid, at, cam, track, face, reid, snap in rows.iterator():
        people.setdefault(pid, _Person(pid)).obs.append(
            _Obs(at, cam, track, _unit(face), _unit(reid), obs_id, snap or "")
        )
    people = {pid: p for pid, p in people.items() if len(p.obs) >= min_obs}
    for p in people.values():
        p.face = _centroid([o.face for o in p.obs])
        p.reid = _centroid([o.reid for o in p.obs])
    return people


def _side_by_side(a: _Person, b: _Person) -> bool:
    """Seen on the same camera at the same moment as different tracks."""
    for oa in a.obs:
        for ob in b.obs:
            if (
                oa.camera_id is not None
                and oa.camera_id == ob.camera_id
                and oa.track_id != ob.track_id
                and abs((oa.at - ob.at).total_seconds()) <= 3
            ):
                return True
    return False


def _linked(a: _Person, b: _Person) -> tuple[bool, str]:
    if a.face is not None and b.face is not None:
        sim = float(a.face @ b.face)
        return sim >= _f("IDENTITY_CLUSTER_FACE_SIM", 0.48), f"face {sim:.2f}"
    if a.reid is not None and b.reid is not None:
        sim = float(a.reid @ b.reid)
        same_day = timezone.localtime(a.first).date() == timezone.localtime(b.first).date()
        gap = max(0.0, (max(a.first, b.first) - min(a.last, b.last)).total_seconds())
        ok = sim >= _f("IDENTITY_CLUSTER_REID_SIM", 0.85) and same_day and gap <= 3600
        return ok, f"reid {sim:.2f}, gap {gap:.0f}s"
    return False, "no comparable embeddings"


def _components(people: dict[int, _Person]) -> list[list[int]]:
    ids = list(people)
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Vectorized face pre-filter keeps this O(n²) cheap for a few hundred unknowns.
    face_ids = [i for i in ids if people[i].face is not None]
    candidates: set[tuple[int, int]] = set()
    if len(face_ids) > 1:
        m = np.stack([people[i].face for i in face_ids])
        sims = m @ m.T
        thr = _f("IDENTITY_CLUSTER_FACE_SIM", 0.48)
        for r, c in zip(*np.where(np.triu(sims, 1) >= thr)):
            candidates.add((face_ids[r], face_ids[c]))
    no_face = [i for i in ids if people[i].face is None and people[i].reid is not None]
    reid_any = [i for i in ids if people[i].reid is not None]
    for a in no_face:
        for b in reid_any:
            if a != b:
                candidates.add((min(a, b), max(a, b)))

    for a, b in candidates:
        ok, _ = _linked(people[a], people[b])
        if ok and not _side_by_side(people[a], people[b]):
            parent[find(a)] = find(b)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)
    return list(groups.values())


def _new_cluster() -> UnknownCluster:
    cluster = UnknownCluster.objects.create(code=uuid.uuid4().hex[:16])
    cluster.code = f"UP-{cluster.pk:04d}"
    cluster.save(update_fields=["code"])
    return cluster


@transaction.atomic
def _persist(people: dict[int, _Person], comps: list[list[int]]) -> list[UnknownCluster]:
    current = dict(
        UnknownClusterMember.objects.filter(
            journey_person_id__in=list(people), cluster__status=ClusterStatus.OPEN
        ).values_list("journey_person_id", "cluster_id")
    )
    used: set[int] = set()
    touched: list[UnknownCluster] = []
    for comp in sorted(comps, key=len, reverse=True):
        votes = Counter(current[p] for p in comp if p in current and current[p] not in used)
        cluster = (
            UnknownCluster.objects.select_for_update().get(pk=votes.most_common(1)[0][0]) if votes else _new_cluster()
        )
        used.add(cluster.pk)
        for pid in comp:
            UnknownClusterMember.objects.update_or_create(journey_person_id=pid, defaults={"cluster": cluster})

        obs = [o for pid in comp for o in people[pid].obs]
        centroid = _centroid([o.face for o in obs])
        cluster.face_centroid = [round(float(v), 6) for v in centroid] if centroid is not None else []
        cluster.person_count = len(comp)
        cluster.observation_count = len(obs)
        cluster.camera_ids = sorted({o.camera_id for o in obs if o.camera_id})
        cluster.first_seen = min(o.at for o in obs)
        cluster.last_seen = max(o.at for o in obs)
        cluster.save()
        touched.append(cluster)

    # Open clusters that lost every member (members re-clustered elsewhere).
    UnknownCluster.objects.filter(status=ClusterStatus.OPEN, members__isnull=True).delete()
    return touched


def _representative(cluster: UnknownCluster):
    from person_journey.models import JourneyPerson
    from django.db.models import Count

    return (
        JourneyPerson.objects.filter(unknown_cluster_membership__cluster=cluster)
        .annotate(n=Count("observations"))
        .order_by("-n", "-latest_seen_at")
        .first()
    )


def _suggest_candidate(cluster: UnknownCluster) -> IdentityDecision | None:
    from identity.services.engine import get_identity_engine, record_decision
    from identity.services.gallery import SFACE_MODEL

    if cluster.status != ClusterStatus.OPEN or not cluster.face_centroid:
        return None
    if cluster.observation_count < int(_f("IDENTITY_CLUSTER_MIN_OBS_FOR_CANDIDATE", 5)):
        return None
    if cluster.candidate_decision_id and cluster.candidate_decision.review_status == ReviewStatus.PENDING:
        return None

    result = get_identity_engine(SFACE_MODEL).identify(cluster.face_centroid, quality=None, source="cluster")
    if result.outcome == DecisionOutcome.UNKNOWN or result.staff_id in (cluster.rejected_staff_ids or []):
        return None
    result.factors["cluster"] = {
        "id": cluster.pk,
        "code": cluster.code,
        "persons": cluster.person_count,
        "observations": cluster.observation_count,
        "cameras": len(cluster.camera_ids or []),
        "first_seen": cluster.first_seen.isoformat() if cluster.first_seen else None,
        "last_seen": cluster.last_seen.isoformat() if cluster.last_seen else None,
    }
    decision = record_decision(
        result,
        journey_person=_representative(cluster),
        camera_name=f"Cluster {cluster.code}",
        policy={
            "action": "cluster_candidate",
            "message": (
                f"{cluster.code}: {cluster.observation_count} observations on "
                f"{len(cluster.camera_ids or [])} camera(s) look like this employee — confirm to link"
            ),
            "gates": [],
        },
        review_status=ReviewStatus.PENDING,
    )
    cluster.candidate_decision = decision
    cluster.save(update_fields=["candidate_decision", "updated_at"])
    return decision


def run_unknown_clustering() -> dict:
    people = _load_people()
    comps = _components(people)
    clusters = _persist(people, comps)
    suggested = 0
    for cluster in clusters:
        try:
            if _suggest_candidate(cluster):
                suggested += 1
        except Exception:
            logger.exception("[identity] Candidate suggestion failed for %s", cluster.code)
    stats = {
        "unknown_persons": len(people),
        "clusters": len(clusters),
        "multi_person_clusters": sum(1 for c in comps if len(c) > 1),
        "candidates_suggested": suggested,
    }
    logger.info("[identity] Unknown clustering: %s", stats)
    return stats


# ── review actions ───────────────────────────────────────────────────────


def _diverse_observations(cluster: UnknownCluster, k: int) -> list[PersonObservation]:
    """Farthest-point sampling: the k face observations that differ most from each other."""
    obs = [
        o
        for o in PersonObservation.objects.filter(
            journey_person__unknown_cluster_membership__cluster=cluster, face_embedding__isnull=False
        )
    ]
    pool = [(o, v) for o in obs if (v := _unit(o.face_embedding)) is not None]
    if not pool:
        return []
    m = np.stack([v for _, v in pool])
    centroid = _unit(cluster.face_centroid) if cluster.face_centroid else None
    chosen = [int(np.argmax(m @ centroid)) if centroid is not None else 0]
    while len(chosen) < min(k, len(pool)):
        # distance of every observation to its nearest already-chosen one
        nearest = (m @ m[chosen].T).max(axis=1)
        nearest[chosen] = np.inf
        chosen.append(int(np.argmin(nearest)))
    return [pool[i][0] for i in chosen]


def cluster_for_decision(decision: IdentityDecision) -> UnknownCluster | None:
    cid = ((decision.factors or {}).get("cluster") or {}).get("id")
    return UnknownCluster.objects.filter(pk=cid).first() if cid else None


def approve_cluster(decision: IdentityDecision, *, staff, user, add_to_gallery: bool) -> dict:
    """Merge every member journey into the employee's and learn from the best observations."""
    from identity.services.gallery import SFACE_MODEL, add_live_entry, push_sface_gallery_to_ml_async
    from person_journey.models import JourneyPerson, PersonType
    from person_journey.services import merge_person_to_staff

    cluster = cluster_for_decision(decision)
    if cluster is None:
        return {}
    merged = []
    for person in JourneyPerson.objects.filter(
        unknown_cluster_membership__cluster=cluster, person_type=PersonType.UNKNOWN
    ):
        linked = merge_person_to_staff(
            person, staff, match_score=decision.face_similarity, reason=f"cluster {cluster.code}"
        )
        merged.append(person.code)
    added = 0
    if add_to_gallery:
        for obs in _diverse_observations(cluster, int(_f("IDENTITY_CLUSTER_GALLERY_ADD", 5))):
            entry, _ = add_live_entry(
                staff=staff,
                embedding=obs.face_embedding,
                quality={},
                camera=obs.camera,
                image_path=obs.snapshot_path,
                decision=decision,
                approved_by=user,
                model_name=SFACE_MODEL,
                push_ml=False,
            )
            added += bool(entry)
        if added:
            push_sface_gallery_to_ml_async()
    cluster.status = ClusterStatus.IDENTIFIED
    cluster.staff = staff
    cluster.save(update_fields=["status", "staff", "updated_at"])
    return {
        "cluster": cluster.code,
        "merged_persons": merged,
        "journey_person_code": linked.code if merged else None,
        "gallery_added": added,
    }


def reject_cluster_candidate(decision: IdentityDecision) -> None:
    cluster = cluster_for_decision(decision)
    if cluster is None or not decision.staff_id:
        return
    rejected = set(cluster.rejected_staff_ids or [])
    rejected.add(decision.staff_id)
    cluster.rejected_staff_ids = sorted(rejected)
    cluster.save(update_fields=["rejected_staff_ids", "updated_at"])


def assign_cluster(cluster: UnknownCluster, *, staff, user, note: str = "", add_to_gallery: bool = True) -> dict:
    """Reviewer names the person directly — still goes through the audit trail."""
    from identity.services.attendance_policy import approve_decision
    from identity.services.gallery import SFACE_MODEL

    decision = IdentityDecision.objects.create(
        source="cluster",
        staff=staff,
        outcome=DecisionOutcome.REVIEW,
        model_name=SFACE_MODEL,
        journey_person=_representative(cluster),
        camera_name=f"Cluster {cluster.code}",
        factors={
            "cluster": {
                "id": cluster.pk,
                "code": cluster.code,
                "persons": cluster.person_count,
                "observations": cluster.observation_count,
                "cameras": len(cluster.camera_ids or []),
            }
        },
        reason="Assigned manually by reviewer",
        policy={"action": "cluster_assigned", "message": f"{cluster.code} assigned to {staff.full_name}", "gates": []},
        review_status=ReviewStatus.PENDING,
    )
    return approve_decision(
        decision, user=user, staff=staff, mark_attendance=False, add_to_gallery=add_to_gallery, note=note
    )


# ── schedule ─────────────────────────────────────────────────────────────

_thread_started = False


def start_clustering_thread() -> None:
    """Run clustering periodically inside `run_background_workers`."""
    global _thread_started
    if _thread_started or not getattr(settings, "IDENTITY_CLUSTERING_ENABLED", True):
        return
    _thread_started = True
    interval = max(60.0, _f("IDENTITY_CLUSTER_INTERVAL_SEC", 300))
    stop = threading.Event()

    def _loop():
        from django.db import connection

        while not stop.wait(interval):
            close_old_connections()
            try:
                run_unknown_clustering()
            except Exception:
                logger.exception("[identity] Unknown clustering failed")
            finally:
                connection.close()

    threading.Thread(target=_loop, daemon=True, name="identity-clustering").start()
    logger.info("[identity] Unknown clustering every %.0fs", interval)
