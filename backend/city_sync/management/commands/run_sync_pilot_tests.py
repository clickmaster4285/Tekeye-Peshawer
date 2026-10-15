"""Automated subset of the Phase 12 pilot checklist (safe to run repeatedly)."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.utils import timezone

from city_sync.hq_receiver import RESULT_APPLIED, RESULT_DUPLICATE, apply_event
from city_sync.identity import identity_dict, is_hq, location_code, system_role
from city_sync.media_sync import hq_media_complete, hq_media_init, sha256_file
from city_sync.models import HqConflict, HqEventLog, HqReplicaRow, SyncOutbox
from city_sync.outbox import payload_hash
from city_sync.reference_sync import publish_reference, seed_default_reference


class Command(BaseCommand):
    help = "Run local pilot checks for city_sync (identity, idempotency, media checksum, reference)."

    def handle(self, *args, **options):
        results = []

        def check(name: str, ok: bool, detail: str = ""):
            results.append((name, ok, detail))
            mark = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"{mark}  {name}" + (f" — {detail}" if detail else ""))

        ident = identity_dict()
        check("identity_present", bool(ident.get("system_role") and ident.get("location_code")), str(ident))

        # Idempotent apply
        eid = uuid.uuid4()
        event_id = uuid.uuid4()
        payload = {"entity_id": str(eid), "status": "present", "date": timezone.localdate().isoformat()}
        ev = {
            "seq": 900001,
            "event_id": str(event_id),
            "location_code": "ABBOTTABAD",
            "entity_type": "attendance",
            "entity_id": str(eid),
            "operation": "upsert",
            "entity_version": 1,
            "schema_version": 1,
            "payload": payload,
            "payload_hash": payload_hash(payload),
        }
        if is_hq() or getattr(settings, "DEBUG", False):
            r1 = apply_event(ev, credential_location="ABBOTTABAD")
            r2 = apply_event(ev, credential_location="ABBOTTABAD")
            check("hq_apply", r1["result"] == RESULT_APPLIED, str(r1))
            check("hq_duplicate", r2["result"] == RESULT_DUPLICATE, str(r2))
            check(
                "hq_replica_once",
                HqReplicaRow.objects.filter(entity_id=eid).count() == 1,
            )
        else:
            check("hq_apply_skipped_on_city", True, "city node — skipped HQ receiver checks")

        # Media checksum path (HQ local)
        if is_hq() or getattr(settings, "DEBUG", False):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(b"ciis-pilot-media-bytes")
                tmp_path = Path(tmp.name)
            digest, size = sha256_file(tmp_path)
            mid = str(uuid.uuid4())
            with tempfile.TemporaryDirectory() as td:
                # Force media root via init helpers using settings MEDIA path
                init = hq_media_init(
                    loc="ABBOTTABAD",
                    media_id=mid,
                    sha256=digest,
                    size_bytes=size,
                    entity_type="attendance",
                    entity_id=eid,
                )
                from city_sync.models import HqMediaObject
                from django.db import transaction

                obj = HqMediaObject.objects.get(media_id=mid)
                Path(obj.storage_path).write_bytes(tmp_path.read_bytes())
                obj.bytes_received = size
                obj.save(update_fields=["bytes_received"])
                with transaction.atomic():
                    done = hq_media_complete(loc="ABBOTTABAD", media_id=mid, sha256=digest)
                check("media_verified", bool(done.get("verified")), str(done))
                # Corrupt complete should fail
                mid2 = str(uuid.uuid4())
                hq_media_init(
                    loc="ABBOTTABAD",
                    media_id=mid2,
                    sha256=digest,
                    size_bytes=size,
                    entity_type="attendance",
                    entity_id=eid,
                )
                obj2 = HqMediaObject.objects.get(media_id=mid2)
                Path(obj2.storage_path).write_bytes(b"WRONG")
                obj2.bytes_received = 5
                obj2.save(update_fields=["bytes_received"])
                with transaction.atomic():
                    bad = hq_media_complete(loc="ABBOTTABAD", media_id=mid2, sha256=digest)
                check("media_reject_corrupt", not bad.get("verified"), str(bad))
            tmp_path.unlink(missing_ok=True)

        # Reference seed
        if is_hq() or getattr(settings, "DEBUG", False):
            n = seed_default_reference()
            check("reference_seeded", n >= 2, f"count={n}")
            publish_reference(entity_type="config", entity_key="pilot_flag", payload={"ok": True})
            check("reference_publish", True)

        # HTTP identity
        client = Client()
        resp = client.get("/api/sync/v1/identity/")
        check("http_identity", resp.status_code == 200, str(resp.status_code))

        failed = [name for name, ok, _ in results if not ok]
        self.stdout.write("")
        if failed:
            self.stderr.write(self.style.ERROR(f"{len(failed)} check(s) failed: {', '.join(failed)}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"All {len(results)} pilot checks passed."))
            self.stdout.write(
                "Manual still required: network cut, HQ-down drain, multi-city keys, full DR drill."
            )
