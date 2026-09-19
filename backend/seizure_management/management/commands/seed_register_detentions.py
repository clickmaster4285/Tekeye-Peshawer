"""
Seed Peshawar DA register detentions (57 rows).

For each row creates:
  - NoteSheet with status=Approved
  - DetentionMemo linked to that note sheet
  - DetentionAssessment with status=Draft (assessment still to be performed)
  - Goods lines parsed from the description

Usage:
  python manage.py seed_register_detentions
  python manage.py seed_register_detentions --dry-run
  python manage.py seed_register_detentions --force
  python manage.py seed_register_detentions --include-duplicates
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from detentions.models import DetentionMemo, DetentionMemoGoodsLine
from seizure_management.models import DetentionAssessment, NoteSheet, NoteSheetItem
from seizure_management.notifications import NOTE_SHEET_FORWARD_TO_LABEL

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "register_detentions_seed.json"

OFFICE = "Model Customs Collectorate, Peshawar"
WAREHOUSE = "Bonded Godown A, Customs House Peshawar"
LOCATION = "PESHAWAR"


def _safe_key(raw: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", (raw or "").strip()).strip("-")
    return (text or "ROW")[:40]


def _dt(date_str: str | None, fallback: str | None = None) -> str:
    """Return 'YYYY-MM-DD HH:MM' from YYYY-MM-DD."""
    src = date_str or fallback
    if not src:
        return timezone.now().strftime("%Y-%m-%d %H:%M")
    try:
        d = datetime.strptime(src[:10], "%Y-%m-%d")
        return d.strftime("%Y-%m-%d 10:00")
    except ValueError:
        return timezone.now().strftime("%Y-%m-%d %H:%M")


def _parse_goods(description: str) -> list[str]:
    """Split numbered goods lines; fall back to whole description."""
    text = (description or "").strip()
    if not text:
        return ["Goods as per DA register"]
    parts = re.split(r"(?:^|\s)(?:\d+[.)]\s*|\d+\))\s*", text)
    items = [p.strip(" ;,.") for p in parts if p and p.strip(" ;,.")]
    if len(items) <= 1:
        return [text]
    return items


def _dept_label(department: str) -> str:
    d = (department or "").strip()
    if d.lower().startswith("apprais"):
        return "Appraisement"
    return "Enforcement"


class Command(BaseCommand):
    help = "Seed DA register detentions with approved note sheets and draft assessments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DATA_FILE),
            help="Path to register_detentions_seed.json",
        )
        parser.add_argument("--dry-run", action="store_true", help="Parse only; no DB writes")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace existing seeded rows matched by note_sheet_no",
        )
        parser.add_argument(
            "--include-duplicates",
            action="store_true",
            help="Also seed rows marked duplicate_of_sno in the JSON",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Seed file not found: {path}")

        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise CommandError("Seed file must be a non-empty JSON array")

        dry = bool(options["dry_run"])
        force = bool(options["force"])
        include_dupes = bool(options["include_duplicates"])

        created = updated = skipped = assessments = 0
        self.stdout.write(f"Loading {len(rows)} register detentions from {path.name}…")

        with transaction.atomic():
            for row in rows:
                if row.get("duplicate_of_sno") and not include_dupes:
                    skipped += 1
                    continue

                sno = int(row.get("sno") or 0)
                da_no = (row.get("da_no") or "").strip()
                case_no = (row.get("case_no") or "").strip()
                if not da_no and not case_no:
                    skipped += 1
                    continue

                department = _dept_label(row.get("department") or "")
                officer = (row.get("officer_name") or "Seizing Officer").strip()
                station = (row.get("station") or "Peshawar").strip()
                description = (row.get("description") or "").strip()
                da_date = row.get("da_date") or row.get("case_date")
                case_date = row.get("case_date") or da_date
                when = _dt(da_date, case_date)

                note_sheet_no = f"NS-REG-{sno:03d}-{_safe_key(da_no)}"
                memo_case = f"DA-{_safe_key(da_no)}"
                memo_ref = f"DET-REG-{sno:03d}"

                existing_ns = NoteSheet.objects.filter(note_sheet_no=note_sheet_no).first()
                if existing_ns and not force:
                    skipped += 1
                    continue

                if dry:
                    if existing_ns:
                        updated += 1
                    else:
                        created += 1
                    assessments += 1
                    continue

                if existing_ns and force:
                    memo = existing_ns.detention_memo
                    if memo:
                        DetentionAssessment.objects.filter(detention_memo=memo).delete()
                        DetentionMemoGoodsLine.objects.filter(memo=memo).delete()
                        memo.delete()
                    existing_ns.items.all().delete()
                    existing_ns.delete()
                    updated += 1
                else:
                    created += 1

                goods = _parse_goods(description)
                subject = f"DA {da_no} — {goods[0][:120]}"

                memo = DetentionMemo.objects.create(
                    case_no=memo_case,
                    reference_number=memo_ref,
                    fir_number=f"SC-{case_no}" if case_no else "",
                    date_time_occurrence=when,
                    place_of_occurrence=f"{station}, Peshawar / Torkham corridor",
                    date_time_detention=when,
                    place_of_detention=OFFICE,
                    detention_type="Detention",
                    directorate=f"MCC Peshawar — {department}",
                    reason_for_detention=description[:2000],
                    location_of_detention=LOCATION,
                    where_deposited=WAREHOUSE,
                    settlement_status="Pending",
                    verification_status="Verified",
                    disposition_status="In Warehouse",
                    brief_facts=(
                        f"Seizure Case No. {case_no} dated {case_date or '—'}. "
                        f"Seizing Officer: {officer} ({station}). Department: {department}. "
                        f"DA No. {da_no}."
                    ),
                    seizing_officer_notes=f"Seeded from DA register — {officer}",
                    detention_notes=(
                        "Detention memo issued after approved note sheet. "
                        "Detention assessment has to be performed."
                    ),
                    purpose_of_detention="Pending valuation / detention assessment",
                    memo_qr_code_number=f"QR-DET-REG-{sno:03d}",
                    memo_qr_code_payload="",
                    created_by="seed_register_detentions",
                    updated_by="seed_register_detentions",
                )
                memo.memo_qr_code_payload = f"/detention-memo/{memo.pk}?print=full"
                memo.save(update_fields=["memo_qr_code_payload", "updated_at"])

                for idx, line in enumerate(goods, start=1):
                    DetentionMemoGoodsLine.objects.create(
                        memo=memo,
                        client_line_id=f"reg-{sno}-{idx}",
                        qr_code_number=f"QR-DET-REG-{sno:03d}-{idx}",
                        description=line[:2000],
                        quantity="",
                        unit="",
                        condition="Detained",
                        perishable=False,
                    )

                approved_at = timezone.now()
                ns = NoteSheet.objects.create(
                    note_sheet_no=note_sheet_no,
                    reference_number=note_sheet_no,
                    status=NoteSheet.STATUS_APPROVED,
                    priority=NoteSheet.PRIORITY_NORMAL,
                    recommendation=NoteSheet.RECOMMENDATION_DETENTION,
                    date_time=when,
                    office=OFFICE,
                    case_no=case_no or memo_case,
                    subject=subject,
                    prepared_by=officer,
                    badge_id=f"REG-{sno:03d}",
                    designation="Seizing Officer",
                    department=department,
                    place_of_inspection=f"{station}",
                    warehouse_shop=WAREHOUSE,
                    inspection_date=when,
                    grounds_of_suspicion=(
                        f"Goods detained under DA {da_no} (Case {case_no}) at {station}. "
                        f"Department: {department}."
                    ),
                    evidence_collected=["Photographs", "Physical Examination", "DA Register Entry"],
                    preliminary_findings=description[:4000],
                    content=(
                        f"Note sheet raised from Peshawar DA register entry S.No {sno}. "
                        f"Recommended: Issue Detention Memo. Assessment pending."
                    ),
                    prepared_signature=officer,
                    prepared_date=(da_date or case_date or "")[:10],
                    forward_to=NOTE_SHEET_FORWARD_TO_LABEL,
                    submitted_at=approved_at,
                    approved_by="Assistant Collector (Preventive)",
                    approved_at=approved_at,
                    approval_remarks=(
                        "Approved. Issue detention memo. Detention assessment has to be performed."
                    ),
                    detention_memo=memo,
                    created_by="seed_register_detentions",
                    updated_by="seed_register_detentions",
                )

                for idx, line in enumerate(goods, start=1):
                    NoteSheetItem.objects.create(
                        note_sheet=ns,
                        client_line_id=f"reg-ns-{sno}-{idx}",
                        qr_code_number=f"QR-NS-REG-{sno:03d}-{idx}",
                        product=line[:2000],
                        quantity="",
                        unit="",
                        condition="Detained",
                        perishable=False,
                        sort_order=idx,
                    )

                DetentionAssessment.objects.create(
                    detention_memo=memo,
                    assessment_date=(case_date or da_date or "")[:10],
                    examining_officer="",
                    goods_condition="Goods under detention — examination pending",
                    valuation_notes="",
                    findings=(
                        "Detention on assessment has to be performed. "
                        "Draft assessment placeholder created from DA register seed."
                    ),
                    document_relevance=DetentionAssessment.RELEVANCE_PENDING,
                    status=DetentionAssessment.STATUS_DRAFT,
                    created_by="seed_register_detentions",
                    updated_by="seed_register_detentions",
                )
                assessments += 1

            if dry:
                transaction.set_rollback(True)

        action = "Dry-run" if dry else "Done"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action}: created={created} updated={updated} skipped={skipped} "
                f"assessments={assessments}"
            )
        )
        self.stdout.write(
            "Note sheets: status=Approved · Assessments: status=Draft "
            "(detention assessment has to be performed)"
        )
