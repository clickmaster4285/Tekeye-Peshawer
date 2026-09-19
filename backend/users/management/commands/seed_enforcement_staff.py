"""
Seed Enforcement Collectorate HQ staff roster into users.Staff.

Source: enforcement_staff_seed.json (67 personnel).

Usage:
  python manage.py seed_enforcement_staff
  python manage.py seed_enforcement_staff --dry-run
  python manage.py seed_enforcement_staff --update
  python manage.py seed_enforcement_staff --create-logins --default-password ChangeMe@123
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from users.models import Staff, User

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "enforcement_staff_seed.json"


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _notes_for(row: dict) -> str:
    parts = []
    domicile = (row.get("domicile") or "").strip()
    if domicile:
        parts.append(f"Domicile: {domicile}")
    enf = row.get("enforcement_joining_date")
    if enf:
        parts.append(f"Joining Enforcement Collectorate: {enf}")
    parts.append("Seeded from Enforcement HQ roster")
    return " | ".join(parts)


class Command(BaseCommand):
    help = "Seed Enforcement Collectorate staff (67) from JSON into Staff records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DATA_FILE),
            help="Path to staff JSON seed file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing to the database",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing Staff matched by employee_id / cnic",
        )
        parser.add_argument(
            "--create-logins",
            action="store_true",
            default=True,
            help="Create login users (username from full name with dots; default on)",
        )
        parser.add_argument(
            "--no-create-logins",
            action="store_true",
            help="Skip creating login users",
        )
        parser.add_argument(
            "--default-password",
            type=str,
            default="123456",
            help="Password for created logins (default: 123456)",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Seed file not found: {path}")

        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise CommandError("Seed file must be a non-empty JSON array")

        dry = bool(options["dry_run"])
        do_update = bool(options["update"])
        create_logins = bool(options["create_logins"]) and not bool(options["no_create_logins"])
        password = options["default_password"] or "123456"

        created = updated = skipped = logins = 0

        self.stdout.write(f"Loading {len(rows)} staff from {path.name}…")

        with transaction.atomic():
            for row in rows:
                full_name = (row.get("full_name") or "").strip()
                if not full_name:
                    skipped += 1
                    continue

                employee_id = (row.get("employee_id") or "").strip() or None
                cnic_raw = "".join(ch for ch in str(row.get("cnic") or "") if ch.isdigit())
                cnic = cnic_raw[:15] if cnic_raw else None

                existing = None
                if employee_id:
                    existing = Staff.objects.filter(employee_id=employee_id).first()
                if existing is None and cnic:
                    existing = Staff.objects.filter(cnic=cnic).first()

                joining = _parse_date(row.get("joining_date")) or timezone.localdate()
                # All Enforcement HQ roster staff are posted under Peshawar station.
                payload = {
                    "full_name": full_name[:150],
                    "father_name": (row.get("father_name") or "")[:150] or None,
                    "designation": (row.get("designation") or "Staff")[:100],
                    "department": (row.get("department") or "Enforcement Collectorate")[:100],
                    "bps": str(row.get("bps") or "")[:10] or None,
                    "phone_primary": (row.get("phone_primary") or "")[:20] or None,
                    "phone_alternate": (row.get("phone_alternate") or "")[:20] or None,
                    "date_of_birth": _parse_date(row.get("date_of_birth")),
                    "qualification": (row.get("qualification") or "")[:200] or None,
                    "current_posting": (row.get("current_posting") or "")[:300] or None,
                    "branch_location": "PESHAWAR",
                    "city": "Peshawar",
                    "address": (row.get("address") or "Peshawar, Khyber Pakhtunkhwa"),
                    "state": "Khyber Pakhtunkhwa",
                    "country": "Pakistan",
                    "gender": (row.get("gender") or "")[:20] or None,
                    "joining_date": joining,
                    "emergency_contact": (row.get("emergency_contact") or row.get("phone_primary") or "")[:100] or None,
                    "personal_number": (row.get("personal_number") or employee_id or "")[:50] or None,
                    "employee_id": employee_id,
                    "job_status": (row.get("job_status") or "Active")[:50],
                    "employment_type": (row.get("employment_type") or "Permanent")[:50],
                    "notes": _notes_for(row),
                    "cnic": cnic,
                    "record_source": Staff.RECORD_SOURCE_DATABASE,
                }

                if existing:
                    if not do_update:
                        skipped += 1
                        continue
                    if dry:
                        updated += 1
                        continue
                    for key, value in payload.items():
                        setattr(existing, key, value)
                    existing.save()
                    staff = existing
                    if staff.user_id:
                        User.objects.filter(pk=staff.user_id).update(
                            location="PESHAWAR",
                            collectorate="Peshawar (Head Office)",
                        )
                    updated += 1
                else:
                    if dry:
                        created += 1
                        continue
                    staff = Staff.objects.create(**payload)
                    created += 1

                if create_logins and not dry and staff.user_id is None:
                    from users.staff_login import unique_employee_login_id

                    username = unique_employee_login_id(staff)
                    if not User.objects.filter(username__iexact=username).exists():
                        phone = payload.get("phone_primary") or "03000000000"
                        desig = (payload.get("designation") or "").strip()
                        role = "GUARD"
                        if desig.upper() in {"HAVILDAR", "HAVALDAR"}:
                            role = "GUARD"
                        elif "LDC" in desig.upper():
                            role = "RECEPTIONIST"
                        user = User.objects.create_user(
                            username=username,
                            password=password,
                            email=f"{username}@ciis.local",
                            role=role,
                            phone=phone,
                            full_name=full_name,
                            cnic=cnic or "",
                            cell_no=phone,
                            designation=desig,
                            employee_id=employee_id or "",
                            location="PESHAWAR",
                            collectorate="Peshawar (Head Office)",
                            is_active=True,
                        )
                        staff.user = user
                        staff.save(update_fields=["user"])
                        logins += 1

            if dry:
                transaction.set_rollback(True)

        action = "Dry-run" if dry else "Done"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}: created={created} updated={updated} skipped={skipped} logins={logins}"
            )
        )
        if dry:
            self.stdout.write("No database changes were written.")
