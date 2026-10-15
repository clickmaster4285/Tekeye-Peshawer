# Phase 12 — Pilot test checklist (DIK/ABT ↔ PEW-HQ)

Run automated checks first:

```bash
# On HQ (Peshawar)
python manage.py migrate city_sync
python manage.py seed_hq_reference
python manage.py run_sync_pilot_tests
```

Then manual tests (record date / pass-fail):

| # | Test | Expected |
|---|------|----------|
| 1 | Create attendance at city | Appears in HQ replica within ~10s (with outbox worker) |
| 2 | Burst create 100 rows | All arrive once; Outbox drains |
| 3 | Stop HQ 10+ min, keep creating | City OK; Outbox drains when HQ returns |
| 4 | Cut network mid-batch | No loss / no dupes after reconnect |
| 5 | Replay same batch | `duplicate`; replica count unchanged |
| 6 | Older version event | `stale` + conflict row |
| 7 | Wrong-city API key | Rejected |
| 8 | Newer schema_version | `retry` / schema_hold (not dead) |
| 9 | Malformed event | `rejected` / dead; others OK |
| 10 | Media upload + interrupt | Resumes offset; verified |
| 11 | Corrupt media bytes | HQ rejects; re-queue |
| 12 | Change HQ reference | City pull within poll interval |
| 13 | Stop city heartbeat | Grid OFFLINE within ~2 min |
| 14 | `record_backup` then heartbeat | Grid shows backup time |
| 15 | `run_reconcile --location ABBOTTABAD` | Report OK or lists mismatches |

## Continuous city processes

```bash
python manage.py run_outbox_worker
python manage.py run_media_worker
python manage.py run_sync_heartbeat
python manage.py run_reference_pull
```

## Multi-city keys (HQ `.env`)

`SYNC_API_KEYS` already includes ABBOTTABAD, DI_KHAN, MARDAN, NOWSHERA, KOHAT.  
Each city deployment sets matching `LOCATION_CODE` + `SYNC_API_KEY`.
