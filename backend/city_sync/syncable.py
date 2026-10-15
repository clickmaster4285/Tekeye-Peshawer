"""Syncable registry — single source of truth for city → HQ entities."""

from __future__ import annotations

import uuid
from typing import Iterable

from django.conf import settings
from django.db import models


def new_entity_id() -> uuid.UUID:
    return uuid.uuid4()


class SyncableModel(models.Model):
    """Optional abstract mixin (Attendance-style). Most models add fields explicitly."""

    entity_id = models.UUIDField(default=new_entity_id, unique=True, editable=False, db_index=True)
    location_code = models.CharField(max_length=64, db_index=True, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        abstract = True

    def ensure_sync_defaults(self) -> None:
        if not self.location_code:
            self.location_code = str(getattr(settings, "LOCATION_CODE", "") or "").strip().upper()


# entity_type -> "app_label.ModelName"
SYNCED_ENTITY_TYPES: dict[str, str] = {
    # HR / attendance
    "attendance": "users.Attendance",
    "staff": "users.Staff",
    "leave_request": "users.LeaveRequest",
    # Visitors / VMS
    "visitor": "visitors.Visitor",
    "vehicle": "visitors.Vehicle",
    "security_alert": "visitors.SecurityAlert",
    "zone_access_log": "visitors.ZoneAccessLog",
    "vms_list_record": "visitors.VmsListRecord",
    # Detentions (legal)
    "detention_memo": "detentions.DetentionMemo",
    "detention_goods_line": "detentions.DetentionMemoGoodsLine",
    "detention_goods_image": "detentions.DetentionMemoGoodsImage",
    "detention_attachment": "detentions.DetentionMemoAttachment",
    "deposit_account_entry": "detentions.DepositAccountEntry",
    # Seizure / case workflow (legal)
    "note_sheet": "seizure_management.NoteSheet",
    "note_sheet_item": "seizure_management.NoteSheetItem",
    "note_sheet_item_image": "seizure_management.NoteSheetItemImage",
    "note_sheet_attachment": "seizure_management.NoteSheetAttachment",
    "detention_assessment": "seizure_management.DetentionAssessment",
    "detention_assessment_attachment": "seizure_management.DetentionAssessmentAttachment",
    "recovery_memo": "seizure_management.RecoveryMemo",
    "seizure_report": "seizure_management.SeizureReport",
    # Cameras / ANPR-style detections
    "detection_event": "cameras.DetectionEvent",
    # Person journey
    "journey_person": "person_journey.JourneyPerson",
    "journey_event": "person_journey.JourneyEvent",
    # Warehouse
    "warehouse_stock_item": "warehouse.WarehouseStockItem",
    "memo_distribution": "warehouse.MemoDistribution",
    "destruction_alert": "warehouse.DestructionAlert",
}

# Legal / workflow — version gaps escalate to conflict at HQ
LEGAL_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "detention_memo",
        "detention_goods_line",
        "detention_goods_image",
        "detention_attachment",
        "deposit_account_entry",
        "note_sheet",
        "note_sheet_item",
        "note_sheet_item_image",
        "note_sheet_attachment",
        "detention_assessment",
        "detention_assessment_attachment",
        "recovery_memo",
        "seizure_report",
    }
)

# FileField / ImageField names to enqueue for media sync (evidence priority)
SYNC_MEDIA_FIELDS: dict[str, list[str]] = {
    "attendance": ["image"],
    "staff": ["profile_image"],
    "detention_memo": ["owner_photo_upload", "driver_photo_upload"],
    "detention_goods_image": ["image"],
    "detention_attachment": ["file"],
    "note_sheet_item_image": ["image"],
    "note_sheet_attachment": ["file"],
    "detention_assessment_attachment": ["file"],
    "detection_event": ["clip", "video"],
    "memo_distribution": ["video"],
}

# Evidence-like media uses higher priority
EVIDENCE_ENTITY_TYPES: frozenset[str] = frozenset(LEGAL_ENTITY_TYPES) | {
    "detection_event",
    "attendance",
}


def synced_model_labels() -> Iterable[str]:
    return SYNCED_ENTITY_TYPES.values()


def entity_type_for_model(model) -> str | None:
    label = f"{model._meta.app_label}.{model._meta.object_name}"
    for entity_type, model_label in SYNCED_ENTITY_TYPES.items():
        if model_label == label:
            return entity_type
    return None


def resolve_model(model_label: str):
    from django.apps import apps

    app_label, model_name = model_label.split(".", 1)
    return apps.get_model(app_label, model_name)
