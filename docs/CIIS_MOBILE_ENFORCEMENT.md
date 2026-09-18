# CIIS mobile device and session enforcement

This document describes how the CIIS PWA stays associated with a registered device after login, how logout ends that session, and how administrators monitor GPS/heartbeat gaps.

It does **not** replace lock/unlock `MobilePhoneSession` rows. Those remain phone-use stretches. Login identity lives on `MobileDevice` + `MobileAccessSession`.

## Device registration

The PWA generates a `device_uuid` once and stores it in `localStorage` (`ciis_device_uuid`). Username is never used as the device id.

`POST /api/auth/login/` with `device_uuid` (PWA only):

1. Authenticates the user.
2. Registers or updates `MobileDevice`.
3. Starts a `MobileAccessSession` (`ACTIVE`).
4. Returns DRF `token` plus `mobile_session`.

Portal login without `device_uuid` does **not** register a device.

## Mobile sessions

Statuses: `ACTIVE`, `LOGGED_OUT`, `EXPIRED`, `REVOKED`, `STALE`.

The backend is authoritative. GPS and heartbeat are accepted only for `ACTIVE` or `STALE` sessions that belong to the authenticated user.

Existing endpoints kept:

- `GET /api/mobile-sessions/` — lock/unlock stretches
- `POST /api/mobile-sessions/transition/`
- `POST /api/mobile-sessions/end/`
- `GET /api/gps/ping/` and `POST /api/mobile/gps/` — same GPS ingestion

## Logout

`POST /api/auth/logout/` marks the access session `LOGGED_OUT`, sets `ended_at`, and records `LOGOUT` / `SESSION_ENDED` / `GPS_STOPPED`.

The DRF auth token is **not** deleted. Portal sessions share that token.

The PWA:

1. Asks “Are you sure you want to sign out of CIIS?”
2. Calls logout while online (or queues a logout event in IndexedDB if offline).
3. Stops GPS and heartbeat.
4. Clears local auth and returns to login.

Attendance is not changed unless existing attendance rules already require it.

## Heartbeat and GPS

`POST /api/mobile/heartbeat/` every 45–60 seconds updates `last_seen_at` / `last_heartbeat_at`. It does **not** write an activity-log row every minute.

`POST /api/mobile/gps/` (alias of GPS ping) stores a point with `event_id`, `device_uuid`, `session_id`, client time, and server receive time. Duplicate `event_id` values are ignored.

GPS and attendance are independent telemetry. GPS active ≠ working; phone offline ≠ absent.

## Offline queue

The PWA stores pending GPS, heartbeat, activity, lock/unlock, attendance, and logout events in IndexedDB (`ciis_mobile_events`). When the network returns, it uploads them. The server ignores duplicate `event_id` values.

## Location permission

The PWA cannot force the OS location toggle. It watches `navigator.permissions` when available and otherwise detects denial on the next GPS attempt.

- Denied: `GPS_PERMISSION_DENIED`
- Granted → denied: `GPS_PERMISSION_REVOKED`

Message shown: “Location permission is required for CIIS field-duty tracking.”

Permission is not requested in a loop.

## PWA uninstall limitation

A web PWA cannot reliably detect uninstall. There is no fake uninstall detector.

Instead the monitor treats missing heartbeats as:

| Threshold (seconds) | Result |
| --- | --- |
| `CIIS_DEVICE_STALE_AFTER` (180) | Device/session `STALE` |
| `CIIS_DEVICE_OFFLINE_ALERT_AFTER` (300) | `DEVICE_OFFLINE` alert |
| `CIIS_DEVICE_OFFLINE_EXTENDED_AFTER` (600) | `DEVICE_OFFLINE_EXTENDED` |

Reconnect creates `DEVICE_RECONNECTED` and resolves the outage alerts. Duplicate alerts for the same outage are not created.

Heartbeat present + GPS missing → `GPS_PROBLEM` / `GPS_OFFLINE`.
Heartbeat missing + GPS missing → `DEVICE_OFFLINE`.

## Admin alerts and permissions

`MobileAlert` rows are scoped by organizational location. Capabilities (extend the map in `logs/enforcement.py` to add roles later):

- `can_view_live_gps`
- `can_view_gps_history`
- `can_view_attendance`
- `can_view_activity_logs`
- `can_view_mobile_devices`
- `can_manage_mobile_devices`
- `can_acknowledge_alerts`
- `can_view_security_alerts`
- `can_manage_roles`

Portal screens:

- Employees (`/employees`) — **Installed** / **Logged in**
- Staff device (`/employees/:id/device`)
- Mobile Alerts (`/employees/mobile-alerts`)

Revoke / terminate / disable-access require `can_manage_mobile_devices`. Field staff cannot read another user’s GPS by changing a URL parameter.

## Multi-device policy

`CIIS_MAX_ACTIVE_MOBILE_DEVICES` (default 1)

`CIIS_MULTI_DEVICE_POLICY`:

- `ALLOW_WITH_ALERT` (default) — login succeeds, `NEW_DEVICE` + `MULTIPLE_DEVICE_LOGIN`
- `BLOCK` — reject extra devices
- `REVOKE_OLD` — revoke previous devices

## Configuration

| Setting | Default |
| --- | --- |
| `CIIS_HEARTBEAT_INTERVAL` | 60 |
| `CIIS_DEVICE_STALE_AFTER` | 180 |
| `CIIS_DEVICE_OFFLINE_ALERT_AFTER` | 300 |
| `CIIS_DEVICE_OFFLINE_EXTENDED_AFTER` | 600 |
| `CIIS_GPS_OFFLINE_AFTER` | 300 |
| `CIIS_MONITOR_INTERVAL` | 60 |
| `CIIS_MAX_ACTIVE_MOBILE_DEVICES` | 1 |
| `CIIS_MULTI_DEVICE_POLICY` | ALLOW_WITH_ALERT |

## Background monitor

Integrated into `python manage.py run_background_workers` (no second scheduler). It calls `logs.enforcement.monitor_mobile_devices`.

## Troubleshooting

- GPS stops after logout or `SESSION_REVOKED`.
- Heartbeat 401/403 with `SESSION_REVOKED` / `DEVICE_REVOKED` signs the PWA out and shows: “Your CIIS mobile session has been revoked by an administrator.”
- Browsers pause PWA GPS in the background; heartbeat gaps are expected if the OS kills the tab. Use stale/offline alerts, not uninstall detection.
- Portal logout and PWA logout are different: PWA logout ends the mobile access session only.
