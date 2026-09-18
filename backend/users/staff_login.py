"""Create a CIIS login from an existing Staff row without duplicating identity fields."""

from __future__ import annotations

import re

from users.models import Staff, User

_VALID_ROLES = {code for code, _label in User.ROLE_CHOICES}
_VALID_LOCATIONS = {code for code, _label in User.LOCATION_CHOICES}

_DESIGNATION_TO_ROLE = {
    "INSPECTOR": "INSPECTOR",
    "GUARD": "GUARD",
    "RECEPTIONIST": "RECEPTIONIST",
    "HR": "HR",
    "HUMAN RESOURCE": "HR",
    "COLLECTOR": "COLLECTOR",
    "DEPUTY COLLECTOR": "DEPUTY_COLLECTOR",
    "ASSISTANT COLLECTOR": "ASSISTANT_COLLECTOR",
    "OPERATION MANAGER": "OPERATION_MANAGER",
    "IT ADMIN": "IT_ADMIN",
    "IT ADMINISTRATOR": "IT_ADMIN",
    "AUDITOR": "AUDITOR",
    "PRAL": "PRAL",
}


def _slug(raw: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", (raw or "").strip()).upper()[:40]


def normalize_login_id(raw: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "", (raw or "").strip()).upper()[:40]


def infer_staff_role(staff: Staff) -> str | None:
    for raw in (staff.role_access_level, staff.system_permissions):
        value = (raw or "").strip().upper().replace(" ", "_").replace("-", "_")
        if value in _VALID_ROLES:
            return value
    designation = (staff.designation or "").strip().upper()
    if designation in _VALID_ROLES:
        return designation
    mapped = _DESIGNATION_TO_ROLE.get(designation)
    if mapped:
        return mapped
    return None


def infer_staff_location(staff: Staff) -> str | None:
    blobs = " ".join(
        filter(
            None,
            [
                staff.branch_location,
                staff.current_posting,
                staff.city,
                staff.state,
            ],
        )
    ).upper()
    for code, label in User.LOCATION_CHOICES:
        if code in blobs.replace(" ", "_") or label.upper() in blobs:
            return code
    return None


def unique_employee_login_id(staff: Staff) -> str:
    """Prefer a name-based username (e.g. UMARFAROOQ); fall back to employee id then EMP0001."""
    bases: list[str] = []
    name = _slug(staff.full_name)
    if name:
        bases.append(name)
    emp_id = _slug(staff.employee_id)
    if emp_id and emp_id not in bases:
        bases.append(emp_id)
    bases.append(f"EMP{staff.pk:04d}")
    for base in bases:
        n = 0
        while True:
            candidate = base if n == 0 else f"{base}{n}"
            user_taken = User.objects.filter(username__iexact=candidate).exists()
            staff_taken = (
                Staff.objects.filter(employee_id__iexact=candidate).exclude(pk=staff.pk).exists()
            )
            if not user_taken and not staff_taken:
                return candidate
            n += 1


def staff_login_preview(staff: Staff) -> dict:
    login_id = unique_employee_login_id(staff)
    role = infer_staff_role(staff)
    location = infer_staff_location(staff)
    email = (staff.email or "").strip() or f"{login_id.lower()}@ciis.local"
    return {
        "staff_id": staff.pk,
        "staff_name": staff.full_name,
        "username": login_id,
        "employee_id": staff.employee_id or login_id,
        "email": email,
        "phone": staff.phone_primary or staff.emergency_contact or "",
        "designation": staff.designation or "",
        "role": role,
        "location": location,
        "role_required": not bool(role),
        "location_required": (role or "INSPECTOR") != "ADMIN" and not bool(location),
        "already_linked": bool(staff.user_id),
    }
