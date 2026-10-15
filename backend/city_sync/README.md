# city_sync — City → HQ synchronization

Implements the CIIS guide through Phases **1–11** foundation (+ pilot helpers).

| Phase | Status | What |
|-------|--------|------|
| 1 Identity | Done | `SYSTEM_ROLE` / `LOCATION_CODE` / `NODE_ID` |
| 2 Outbox | Done | Transactional Outbox + Attendance sync columns |
| 3 Worker | Done | `run_outbox_worker` |
| 4 HQ API | Done | `/api/sync/v1/events` + replica / conflicts / cursor |
| 5 Media | Done | `MediaQueue` → chunked upload → HQ verify under `{LOCATION}/{yyyy}/{mm}/` |
| 6 Reference | Done | HQ `HqReferenceItem` → city `CityReferenceCache` |
| 7 Grid API | Done | `/api/sync/v1/cities/` health + backup/reconcile fields |
| 8 Backup | Done | `record_backup` + heartbeat `last_backup_at` |
| 9 Audit | Done | append-only `SyncAuditLog` |
| 10 Reconcile | Done | `run_reconcile` attendance summary compare |
| 11 Security | Done | per-city `SYNC_API_KEYS`, location-bound auth |
| 12 Pilot | Done | `run_sync_pilot_tests` + `PILOT_TEST_CHECKLIST.md` |
| 13 Rollout | Config | Keys for ABBOTTABAD, DI_KHAN, MARDAN, NOWSHERA, KOHAT |

## Roles

| Codebase | Role | Location |
|----------|------|----------|
| `ciis-peshawar` | `hq` | `PESHAWAR` |
| `ciis-abbottabad` | `city` | `ABBOTTABAD` |

## HQ startup

```bash
cd ciis-peshawar/backend
python manage.py migrate city_sync
python manage.py seed_hq_reference
python manage.py runserver 8000
# optional checks
python manage.py run_sync_pilot_tests
```

## City startup (Abbottabad)

```bash
cd ciis-abbottabad/backend
python manage.py migrate city_sync
# four workers (separate terminals or process manager)
python manage.py run_outbox_worker
python manage.py run_media_worker
python manage.py run_sync_heartbeat
python manage.py run_reference_pull
```

## Multi-city

HQ `.env`:

```env
SYNC_API_KEYS=ABBOTTABAD=...,DI_KHAN=...,MARDAN=...,NOWSHERA=...,KOHAT=...
```

Each city sets matching `LOCATION_CODE` + `SYNC_API_KEY` + `HQ_SYNC_URL`.

## Media storage at HQ

```
MEDIA_ROOT/hq_sync_media/{LOCATION_CODE}/{yyyy}/{mm}/{media_id}
```

or `SYNC_HQ_MEDIA_ROOT` if set.

## Full-system entity sync

**27 entity types** are registered (attendance, staff, visitors, detentions, seizures, detections, journey, warehouse). See `SYNCED_TABLES.md`.

To push **existing** city rows to HQ once:

```bash
# on city
python manage.py bootstrap_sync_outbox
# then run outbox (+ media) workers
python manage.py run_outbox_worker
python manage.py run_media_worker
```

## Testing

See `PILOT_TEST_CHECKLIST.md`.
