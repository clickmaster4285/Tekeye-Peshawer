# City rollout checklist (Stage 5)

Moves a city server onto the one Peshawar codebase and connects it to Peshawar HQ.
Do the **test server first**, then **Abbottabad**, then the other cities one by one.

Write the date and OK / problem next to each step.

---

## Before you start (Peshawar side)

1. Peshawar HQ runs the latest `multi-site-sync` code, `python manage.py migrate` is done, and the server is running.
2. `HQ_PUBLIC_URL` in Peshawar's `backend/.env` is an address **the city can reach** (for the pilot: `http://192.168.88.45:8000`).
3. From the city server, open `http://<peshawar>:8000/api/sync/v1/identity/` in a browser.
   It must show `"system_role": "hq"`. If it does not open, fix the network or firewall first. Nothing else will work without it.

## 1. Back up the city database (do not skip)

```bash
pg_dump -Fc -U postgres -d "TEKEYE(ABBOTTABAD)" -f abbottabad_before_sync.dump
```

Keep the file somewhere safe. The `media` folder is not changed by this rollout.

## 2. Stop the city app

Stop the Django server and the four sync workers (if they were running).

## 3. Switch the code to the Peshawar repo

The city folder is a git clone of the old city repo. Add the Peshawar repo next to it.
`.env` and `media/` are not in git, so they stay as they are.

```bash
cd <city project folder>
git status                      # must say "nothing to commit". If not, STOP and ask.
git branch --show-current       # write this down (Abbottabad: UmerPC). You need it to roll back.
git remote add peshawar https://github.com/clickmaster4285/Tekeye-Peshawer.git
git fetch peshawar
git checkout -b multi-site-sync peshawar/multi-site-sync
cd backend && pip install -r requirements.txt
```

Build and deploy the frontend the usual way (`npm install` and `npm run build` in `frontend/`).

Later updates on this server: `git pull peshawar multi-site-sync`.

## 4. Add the city at Peshawar and set its `.env`

1. Peshawar → **Settings → Locations & Sync → Add location**: code (e.g. `ABBOTTABAD`), name, and the city's address (e.g. `http://192.168.120.13:8000`).
2. Copy the 5 lines it shows (`SYSTEM_ROLE` … `SYNC_API_KEY`). The key is shown **only once**.
3. In the city's `backend/.env`, delete the old lines with these names and paste the new ones.
   Do not change `DB_NAME` or the other settings.

## 5. Update the city database

```bash
python manage.py migrate
```

`migrate` encrypts NVR passwords, staff bank/salary details and sync copies. The first time,
it creates this site's own key in `backend/.keys/field_encryption.key`.

**Copy `backend/.keys/` to a safe place now (USB / another server), not next to the DB backup.**
Without `field_encryption.key` the encrypted data can never be read again. At Peshawar the
folder also holds `view_pass_ed25519.pem` (signs City Cameras passes).

Then, once, encrypt the old sync rows (it can take a while on a big database; it is safe to
stop with Ctrl+C and run again):

```bash
python manage.py encrypt_fields
python manage.py encrypt_fields --status   # every line should show "plain": 0
```

## 6. Run the pre-flight check

```bash
python manage.py city_sync_check
```

Every line must be `OK`, with no `FAIL`. Before step 7, warnings like "no heartbeat yet" are normal.
Each `FAIL` line says what to fix (`->`). Fix it and run the check again.

## 7. Start the city app and the sync workers

Start Django as usual, plus these four (separate windows or the process manager):

```bash
python manage.py run_outbox_worker
python manage.py run_media_worker
python manage.py run_sync_heartbeat
python manage.py run_reference_pull
```

After 1 minute run `python manage.py city_sync_check` again. It should now say **READY**.

## 8. Check it works

At Peshawar, **Locations & Sync**:

- [ ] The city shows **Online** and **Last test** is green (menu → Test link).
- [ ] **Waiting at city** goes down. A city with old data can have a big backlog, so let it run (it can take hours).
- [ ] Optional: **Full history** to also copy all old records and images. Start it after working hours.

City → Peshawar:

- [ ] Mark one attendance at the city. It appears at Peshawar (Attendance, Location = the city) within a minute.

Peshawar → city:

- [ ] At Peshawar, add a test staff member with photos and set **Works at** to the city.
      Within a minute they appear at the city with photos, and **Sent to city** shows *Up to date*.
- [ ] The test person walks past a city camera and is recognized there (not at Peshawar).
- [ ] Edit the test staff member at Peshawar (e.g. designation). The change shows at the city.
- [ ] Change **Works at** back to Peshawar (transfer). At the city they show as transferred, without face data.

If **Sent to city** shows *failed*, hover it for the reason.

## If something goes wrong: roll back

```bash
# stop the app and workers first
git checkout UmerPC                        # the branch you wrote down in step 3
pg_restore --clean -U postgres -d "TEKEYE(ABBOTTABAD)" abbottabad_before_sync.dump
# put the old .env lines back, then start the app
```

Anything entered at the city after step 7 is lost by the restore, so roll back early or not at all.
Keep `backend/.keys/` after a restore: rows encrypted before the backup still need that key.
Then on Peshawar's Locations page, **Pause** the city until the problem is fixed.

---

## Rollout log

| City | Date | Done by | Result |
|------|------|---------|--------|
| Test server (192.168.88.48) | | | |
| Abbottabad | | | |
| DI Khan | | | |
| Thakot | | | |
| DDK | | | |
| Mardan | | | |
| Nowshera | | | |
