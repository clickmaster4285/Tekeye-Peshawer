# Synced tables (full business coverage)

Outbox sync covers **every concrete Django model** in local apps, except exclusions below.

## Excluded (not synced)

| App / area | Why |
|------------|-----|
| `django.contrib.*`, sessions, admin, contenttypes | Framework internals |
| `authtoken` | API tokens (machine-local) |
| `city_sync` | Sync meta tables (Outbox, HQ replicas, …) |
| `ops_central` | HQ remote-server registry |
| `realtime` | Ephemeral realtime |

## Included

All other local apps, including:

- users (User, Staff, Attendance, Leave*, Payroll*, …)
- visitors, detentions, seizure_management, warehouse
- cameras (Site, Nvr, Camera, DetectionEvent, …)
- person_journey, object_tracking, recognition
- logs (activity / mobile)
- gps_tracking, video_recovery, camera_health
- infrastructure_monitoring, voice_agent, requests_support

Entity types are auto-named (`leave_type`, `camera`, …). Legacy names (`attendance`, `detection_event`, …) are kept for already-synced entities.

## Prepare (both HQ and city DBs)

```bash
python manage.py migrate city_sync
python manage.py prepare_full_table_sync
```

## Bootstrap historical rows (city only — run on Abbottabad `.45`)

Copy updated `city_sync` code to the city server, then:

```bash
python manage.py migrate city_sync
python manage.py prepare_full_table_sync
python manage.py bootstrap_sync_outbox
python manage.py run_city_sync
```

City `.env` must use `DB_NAME=TEKEYE(ABBOTTABAD)`, `SYSTEM_ROLE=city`, and
`HQ_SYNC_URL=http://192.168.88.48:8000/api/sync/v1`.

## Notes

- HQ always stores copies in `HqReplicaRow` (sync spine).
- With `SYNC_HQ_CITY_DB_ENABLED=True`, HQ also creates a **separate Postgres DB**
  per connected city (`TEKEYE_HQ_{LOCATION}`) and projects applied events into
  real tables. Both methods stay active.
- Media stays on Peshawar: `MEDIA_ROOT/hq_sync_media/{LOCATION}/…` and mirrored
  under `MEDIA_ROOT/city_dbs/{LOCATION}/media/` when `SYNC_HQ_CITY_MEDIA_MIRROR=True`.
- Soft-delete only (`is_deleted=True`) on synced models.

## HQ city databases

```bash
# On Peshawar HQ — create/migrate DBs for all SYNC_API_KEYS cities
python manage.py ensure_hq_city_databases
# Also backfill tables from existing replicas
python manage.py ensure_hq_city_databases --project
# One city only
python manage.py ensure_hq_city_databases --location ABBOTTABAD --project
```
