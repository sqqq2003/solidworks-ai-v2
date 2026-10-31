# HANDOFF — A2 1:10 / 1:20 retest @ 9dd6908 / 4344f22 COM

## Tip
- COM/session/owned: `4344f222a2070d0f79082d219377e840f06ca30f`
- Drawing overlay tip: `9dd6908910c52fa22599305110fc93616ed56037` (annotation/com_access/model_document dual-cast)
- DESKTOP_REPO detached at 4344f22 with those files checked out from tip (blob match verified)

## Cells (retry after cleanup; honest)
- **A2_1-10**: `failed` — AttributeError: GetAnnotation in sw_compat.annotation.set_annotation_position → read_com_member. Inventory OK; assembly opened; export reached InsertNote. No DISP_E_MEMBERNOTFOUND (-2147352573) in traceback.
- **A2_1-20**: `failed` — same AttributeError: GetAnnotation.

## MEMBERNOTFOUND?
- **No** (retry). Prior D4 fail was DISP_E_MEMBERNOTFOUND on GetAnnotation invoke. Tip 9dd6908 wraps via read_com_member `declared()` gate; undeclared GetAnnotation on InsertNote return → AttributeError before COM invoke. Fix incomplete for live note objects.

## Attempt1 (archived attempt1_160735)
- A2_1-10 failed_inventory (GetNext disconnect / probe OSError 5 during rebind)
- A2_1-20 writer lock (leftover owned PID)

## OUT
- D:\工程\钣金导入\lxy_drawing_a2_9dd6908
- Docs: C:\Users\yue\Documents\lxy_drawing_a2_9dd6908

## Do not claim
- Production drawing pass. Mode: explicit_partial_model_test. manufacturing_approved=false.