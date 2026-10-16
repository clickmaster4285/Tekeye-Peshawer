"""Pre-flight check for a city server (Stage 5 rollout). Read-only: changes nothing.

python manage.py city_sync_check
"""

from __future__ import annotations

from datetime import timedelta
from email.utils import parsedate_to_datetime

import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from city_sync.identity import allowed_location_codes, is_city, location_code, system_role


class Command(BaseCommand):
    help = "Check that this city server is ready to sync with Peshawar HQ (changes nothing)."

    def handle(self, *args, **options):
        self.failed = 0
        self.warned = 0

        self.stdout.write(f"\nCity sync check for {location_code() or '?'} ({getattr(settings, 'NODE_ID', '') or '?'})\n")
        if not self._check_env():
            return self._summary()
        self._check_migrations()
        self._check_media()
        if self._check_hq():
            self._check_key()
        self._check_workers()
        return self._summary()

    # -- output -----------------------------------------------------------

    def ok(self, msg: str) -> None:
        self.stdout.write(self.style.SUCCESS("  OK    ") + msg)

    def warn(self, msg: str, fix: str = "") -> None:
        self.warned += 1
        self.stdout.write(self.style.WARNING("  WARN  ") + msg + (f"\n        -> {fix}" if fix else ""))

    def fail(self, msg: str, fix: str = "") -> None:
        self.failed += 1
        self.stdout.write(self.style.ERROR("  FAIL  ") + msg + (f"\n        -> {fix}" if fix else ""))

    def _summary(self) -> None:
        self.stdout.write("")
        if self.failed:
            self.stdout.write(self.style.ERROR(f"NOT READY: {self.failed} problem(s), {self.warned} warning(s)."))
        elif self.warned:
            self.stdout.write(self.style.WARNING(f"READY with {self.warned} warning(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("READY: this city can sync with Peshawar."))

    # -- checks -----------------------------------------------------------

    def _check_env(self) -> bool:
        self.stdout.write("\n.env")
        if not is_city():
            self.fail(f"SYSTEM_ROLE is '{system_role() or 'empty'}'", "set SYSTEM_ROLE=city in backend/.env")
            return False
        self.ok("SYSTEM_ROLE=city")
        loc = location_code()
        if not loc:
            self.fail("LOCATION_CODE is empty", "copy the .env lines from Peshawar's Locations & Sync page")
            return False
        if loc not in allowed_location_codes():
            self.fail(f"LOCATION_CODE={loc} is not in ALLOWED_LOCATION_CODES", "check the spelling, e.g. ABBOTTABAD")
            return False
        self.ok(f"LOCATION_CODE={loc}")
        if not getattr(settings, "NODE_ID", ""):
            self.fail("NODE_ID is empty", "copy the .env lines from Peshawar's Locations & Sync page")
            return False
        self.ok(f"NODE_ID={settings.NODE_ID}")
        if not getattr(settings, "HQ_SYNC_URL", ""):
            self.fail("HQ_SYNC_URL is empty", "copy the .env lines from Peshawar's Locations & Sync page")
            return False
        self.ok(f"HQ_SYNC_URL={settings.HQ_SYNC_URL}")
        from city_sync.worker import _load_api_key

        try:
            has_key = bool(_load_api_key())
        except RuntimeError as exc:
            self.fail(str(exc))
            return False
        if not has_key:
            self.fail("SYNC_API_KEY is empty", "on Peshawar's Locations & Sync page use 'New key' and copy it here")
            return False
        self.ok("SYNC_API_KEY is set")
        return True

    def _check_migrations(self) -> None:
        self.stdout.write("\nDatabase")
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:5])
            more = f" (+{len(plan) - 5} more)" if len(plan) > 5 else ""
            self.fail(f"{len(plan)} migration(s) not applied: {names}{more}", "run: python manage.py migrate")
        else:
            self.ok(f"all migrations applied ({connection.settings_dict.get('NAME')})")

    def _check_media(self) -> None:
        from django.core.files.base import ContentFile

        try:
            saved = default_storage.save("_city_sync_check.tmp", ContentFile(b"ok"))
            default_storage.delete(saved)
            self.ok(f"media folder is writable ({settings.MEDIA_ROOT})")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"cannot write to the media folder: {exc}", "photos from Peshawar are saved here")

    def _check_hq(self) -> bool:
        self.stdout.write("\nPeshawar HQ")
        url = f"{settings.HQ_SYNC_URL}/identity/"
        try:
            resp = requests.get(url, timeout=10)
        except requests.RequestException as exc:
            self.fail(f"cannot reach {url}: {exc.__class__.__name__}", "check the IP/port, firewall and that HQ is running")
            return False
        if not resp.ok:
            self.fail(f"{url} answered HTTP {resp.status_code}", "HQ_SYNC_URL must end with /api/sync/v1")
            return False
        try:
            ident = resp.json()
        except ValueError:
            self.fail(f"{url} did not answer like a CIIS server", "HQ_SYNC_URL must end with /api/sync/v1")
            return False
        if ident.get("system_role") != "hq":
            self.fail(
                f"that server is '{ident.get('system_role')}' ({ident.get('location_code')}), not the head office",
                "point HQ_SYNC_URL at Peshawar",
            )
            return False
        self.ok(f"reached HQ {ident.get('location_code')} ({ident.get('node_id', '')})")

        date_header = resp.headers.get("Date")
        if date_header:
            try:
                drift = abs((timezone.now() - parsedate_to_datetime(date_header)).total_seconds())
            except (TypeError, ValueError):
                drift = None
            limit = max(float(getattr(settings, "SYNC_MAX_CLOCK_DRIFT_SECONDS", 5)), 60)
            if drift is not None and drift > limit:
                self.warn(f"this clock is {int(drift)}s off from Peshawar", "fix the server time (attendance times depend on it)")
            elif drift is not None:
                self.ok(f"clock matches Peshawar ({int(drift)}s difference)")
        return True

    def _check_key(self) -> None:
        from city_sync.models import CityControlState
        from city_sync.worker import _load_api_key

        cursor = CityControlState.load().downlink_seq
        try:
            resp = requests.get(
                f"{settings.HQ_SYNC_URL}/downlink",
                params={"after": cursor},
                headers={"Authorization": f"Bearer {_load_api_key()}"},
                timeout=15,
            )
        except requests.RequestException as exc:
            self.fail(f"key check failed: {exc.__class__.__name__}")
            return
        if resp.status_code in (401, 403):
            detail = ""
            try:
                detail = (resp.json() or {}).get("detail", "")
            except ValueError:
                pass
            self.fail(
                f"Peshawar rejected the key ({detail or resp.status_code})",
                f"add {location_code()} on Locations & Sync (or 'New key') and copy the .env lines again",
            )
            return
        if not resp.ok:
            self.fail(f"Peshawar answered HTTP {resp.status_code} to the key check", "update Peshawar to the same code version")
            return
        waiting = (resp.json() or {}).get("count", 0)
        self.ok("Peshawar accepts this server's key")
        if waiting:
            self.warn(f"{waiting} change(s) from Peshawar not applied here yet", "start run_sync_heartbeat; they apply on the next heartbeat")

    def _check_workers(self) -> None:
        from city_sync.models import CityControlState, SyncOutbox

        self.stdout.write("\nSync workers")
        state = CityControlState.load()
        last = state.last_hq_contact_at
        interval = float(getattr(settings, "SYNC_HEARTBEAT_INTERVAL", 30))
        if last is None:
            self.warn("no heartbeat has reached Peshawar yet", "start: python manage.py run_sync_heartbeat")
        elif timezone.now() - last > timedelta(seconds=max(interval * 4, 120)):
            self.warn(f"last heartbeat {timezone.localtime(last):%Y-%m-%d %H:%M}", "is run_sync_heartbeat running?")
        else:
            self.ok(f"heartbeat running (last {timezone.localtime(last):%H:%M:%S})")
        if state.is_paused:
            self.warn("Peshawar has paused this location", "resume it on the Locations & Sync page")

        loc = location_code()
        rows = SyncOutbox.objects.filter(location_code=loc)
        dead = rows.filter(status=SyncOutbox.STATUS_DEAD).count()
        stale = rows.filter(
            status__in=[SyncOutbox.STATUS_PENDING, SyncOutbox.STATUS_SENDING],
            created_at__lt=timezone.now() - timedelta(minutes=10),
        ).count()
        if stale:
            self.warn(f"{stale} record(s) waiting more than 10 minutes", "is run_outbox_worker running?")
        else:
            self.ok("records are not piling up")
        if dead:
            self.warn(f"{dead} record(s) failed for good", "see the Sync Monitor; Peshawar shows the reason")
