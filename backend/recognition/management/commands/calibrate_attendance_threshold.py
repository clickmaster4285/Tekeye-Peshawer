"""Suggest the CCTV match threshold from HR-reviewed face samples.

Approved samples are genuine probes (known person); rejected samples are impostor
probes for the person they were mistaken for. Each probe is scored exactly like the
live worker scores it (mean of the top vectors per person), against the gallery with
the probe's own vector left out. Nothing is changed; the result is printed as an
env line to set.
"""

from __future__ import annotations

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from recognition.models import FaceEnrollment, FaceSample
from recognition.services.gallery_index import MATCH_MARGIN, _normalize, identity_scores


class Command(BaseCommand):
    help = "Suggest ATTENDANCE_CCTV_SIMILARITY_THRESHOLD from reviewed CCTV face samples."

    def add_arguments(self, parser):
        parser.add_argument(
            "--target-far",
            type=float,
            default=0.0,
            help="Highest acceptable share of impostor probes that would be accepted (default 0).",
        )
        parser.add_argument(
            "--safety",
            type=float,
            default=0.02,
            help="Added above the lowest threshold that meets --target-far (default 0.02).",
        )
        parser.add_argument("--min-probes", type=int, default=30)

    def handle(self, *args, **opts):
        model_name = getattr(settings, "ATTENDANCE_INSIGHTFACE_MODEL", "buffalo_l")
        keys, vectors, sample_ids = self._gallery(model_name)
        if not keys:
            self.stdout.write(self.style.ERROR("No trained enrollments — nothing to calibrate against."))
            return
        matrix = np.stack(vectors)
        keys_arr = np.array(keys)
        ids_arr = np.array(sample_ids)

        genuine: list[tuple[float, float]] = []  # (own score, best other score)
        impostor: list[float] = []
        reviewed = FaceSample.objects.filter(
            model_name=model_name,
            status__in=[FaceSample.STATUS_APPROVED, FaceSample.STATUS_REJECTED],
        ).only("id", "status", "staff_id", "suggested_staff_id", "embedding")
        for sample in reviewed:
            probe = _normalize(sample.embedding or [])
            if probe.size != matrix.shape[1]:
                continue
            keep = ids_arr != sample.id
            scores = identity_scores(zip(keys_arr[keep], matrix[keep] @ probe))
            if sample.status == FaceSample.STATUS_APPROVED:
                own = scores.pop(f"staff-{sample.staff_id}", None)
                if own is None:
                    continue  # this person has no trained photos, so the live system cannot match them
                other = max(scores.values(), default=-1.0)
                genuine.append((own, other))
                impostor.append(other)
            elif sample.suggested_staff_id:
                mistaken = scores.get(f"staff-{sample.suggested_staff_id}")
                if mistaken is not None:
                    impostor.append(mistaken)

        current = float(getattr(settings, "ATTENDANCE_CCTV_SIMILARITY_THRESHOLD", 0.38))
        self.stdout.write(
            f"Model {model_name} · gallery {len(keys)} vectors · "
            f"{len(genuine)} genuine probes · {len(impostor)} impostor scores"
        )
        if len(genuine) < opts["min_probes"] or len(impostor) < opts["min_probes"]:
            self.stdout.write(self.style.WARNING(
                f"Fewer than {opts['min_probes']} probes on one side: review more samples on the "
                "Face Enrollment page before trusting this result."
            ))
        if not genuine or not impostor:
            self._lookalikes(model_name)
            return

        def rates(threshold: float) -> tuple[float, float]:
            # A genuine probe is missed when it is under the threshold or too close to someone else.
            missed = sum(1 for own, other in genuine if own < threshold or own - other < MATCH_MARGIN)
            accepted = sum(1 for score in impostor if score >= threshold)
            return missed / len(genuine), accepted / len(impostor)

        grid = [round(t, 2) for t in np.arange(0.20, 0.75, 0.01)]
        meeting = [t for t in grid if rates(t)[1] <= opts["target_far"]]
        recommended = round(min(meeting) + opts["safety"], 2) if meeting else None

        self.stdout.write("\nthreshold  missed-punch  false-accept")
        shown = sorted({round(current, 2), *(t for t in grid if round(t * 100) % 5 == 0)}
                       | ({recommended} if recommended else set()))
        for t in shown:
            frr, far = rates(t)
            tags = []
            if abs(t - current) < 1e-6:
                tags.append("current")
            if recommended is not None and abs(t - recommended) < 1e-6:
                tags.append("recommended")
            self.stdout.write(f"  {t:.2f}      {frr:6.1%}        {far:6.1%}   {' '.join(tags)}")

        self.stdout.write(
            f"\nHighest impostor score {max(impostor):.3f} · lowest genuine score "
            f"{min(own for own, _ in genuine):.3f}"
        )
        if recommended is None:
            self.stdout.write(self.style.ERROR(
                "No threshold up to 0.74 keeps impostors out — check the rejected samples for review mistakes."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nSet in .env:  ATTENDANCE_CCTV_SIMILARITY_THRESHOLD={recommended}"))
        self._lookalikes(model_name)

    def _gallery(self, model_name: str):
        """Same vectors the live gallery loads, tagged with the sample id they came from (0 = photo)."""
        keys, vectors, sample_ids = [], [], []
        trained = set()
        for enrollment in FaceEnrollment.objects.filter(is_trained=True, embedding__isnull=False):
            trained.add(enrollment.staff_id)
            for vector in [enrollment.embedding, *(enrollment.embeddings or [])]:
                arr = _normalize(vector or [])
                if arr.size and float(np.linalg.norm(arr)) > 0:
                    keys.append(enrollment.gallery_key)
                    vectors.append(arr)
                    sample_ids.append(0)
        for sample in FaceSample.objects.filter(
            status=FaceSample.STATUS_APPROVED, model_name=model_name, staff_id__in=trained
        ).only("id", "staff_id", "embedding"):
            arr = _normalize(sample.embedding or [])
            if arr.size and float(np.linalg.norm(arr)) > 0:
                keys.append(f"staff-{sample.staff_id}")
                vectors.append(arr)
                sample_ids.append(sample.id)
        dims = {v.size for v in vectors}
        if len(dims) > 1:
            # Mixed models in the gallery: keep the common size only.
            common = max(dims, key=lambda d: sum(1 for v in vectors if v.size == d))
            picked = [i for i, v in enumerate(vectors) if v.size == common]
            keys = [keys[i] for i in picked]
            vectors = [vectors[i] for i in picked]
            sample_ids = [sample_ids[i] for i in picked]
        return keys, vectors, sample_ids

    def _lookalikes(self, model_name: str):
        """Enrolled people whose photos are close: the pairs most likely to be confused."""
        enrollments = list(
            FaceEnrollment.objects.filter(is_trained=True, embedding__isnull=False).select_related("staff")
        )
        means = [(e.staff.full_name, _normalize(e.embedding)) for e in enrollments]
        means = [(name, vec) for name, vec in means if vec.size]
        if len(means) < 2:
            return
        names = [name for name, _ in means]
        sims = np.stack([vec for _, vec in means])
        sims = sims @ sims.T
        pairs = sorted(
            ((float(sims[i, j]), names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))),
            reverse=True,
        )[:5]
        self.stdout.write("\nClosest enrolled pairs (photo vs photo):")
        for score, a, b in pairs:
            self.stdout.write(f"  {score:.3f}  {a} ↔ {b}")
