# Synced entity registry (full system)

City → HQ Outbox sync is enabled for:

| entity_type | Django model | Media fields |
|-------------|--------------|--------------|
| `attendance` | `users.Attendance` | `image` |
| `staff` | `users.Staff` | `profile_image` |
| `leave_request` | `users.LeaveRequest` | — |
| `visitor` | `visitors.Visitor` | — |
| `vehicle` | `visitors.Vehicle` | — |
| `security_alert` | `visitors.SecurityAlert` | — |
| `zone_access_log` | `visitors.ZoneAccessLog` | — |
| `vms_list_record` | `visitors.VmsListRecord` | — |
| `detention_memo` | `detentions.DetentionMemo` | owner/driver photos |
| `detention_goods_line` | `detentions.DetentionMemoGoodsLine` | — |
| `detention_goods_image` | `detentions.DetentionMemoGoodsImage` | `image` |
| `detention_attachment` | `detentions.DetentionMemoAttachment` | `file` |
| `deposit_account_entry` | `detentions.DepositAccountEntry` | — |
| `note_sheet` | `seizure_management.NoteSheet` | — |
| `note_sheet_item` | `seizure_management.NoteSheetItem` | — |
| `note_sheet_item_image` | `seizure_management.NoteSheetItemImage` | `image` |
| `note_sheet_attachment` | `seizure_management.NoteSheetAttachment` | `file` |
| `detention_assessment` | `seizure_management.DetentionAssessment` | — |
| `detention_assessment_attachment` | `seizure_management.DetentionAssessmentAttachment` | `file` |
| `recovery_memo` | `seizure_management.RecoveryMemo` | — |
| `seizure_report` | `seizure_management.SeizureReport` | — |
| `detection_event` | `cameras.DetectionEvent` | `clip`, `video` |
| `journey_person` | `person_journey.JourneyPerson` | — |
| `journey_event` | `person_journey.JourneyEvent` | — |
| `warehouse_stock_item` | `warehouse.WarehouseStockItem` | — |
| `memo_distribution` | `warehouse.MemoDistribution` | `video` |
| `destruction_alert` | `warehouse.DestructionAlert` | — |

Legal entities use stricter HQ conflict rules (version gaps).

## Not synced (by design)

- Continuous NVR recordings (separate backup)
- ML caches / ephemeral worker state
- Local-only UI preferences
