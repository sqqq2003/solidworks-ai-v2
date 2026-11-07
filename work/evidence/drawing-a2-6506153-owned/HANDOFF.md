# HANDOFF — A2 1:10 / 1:20 retest @ 6506153 / 4344f22 COM

## Tip
- COM/session/owned: `4344f222a2070d0f79082d219377e840f06ca30f`
- Drawing tip: `6506153dde3c642d7b71bd8bff8c2436279c908a` (com_access/annotation IDispatch for undeclared GetAnnotation)
- DESKTOP_REPO detached at 4344f22; annotation/com_access blobs match tip
- Did not modify sw_session / sw_owned_launch

## Cells (honest)
- **A2_1-10**: `failed` — SessionOwnershipError: unowned documents appeared in task process (at save_reopen/close_document/guard). SLDDRW written (~13.3MB). No PDF/sheet_readback.
- **A2_1-20**: `failed` — same SessionOwnershipError at save_reopen/close_document/guard. SLDDRW written (~13.3MB). No PDF/sheet_readback.

## Annotation / MEMBERNOTFOUND
- **AttributeError GetAnnotation: gone**
- **DISP_E_MEMBERNOTFOUND (-2147352573): gone**
- Export reached InsertNote + set_annotation_position and continued to save_reopen; fail is owned-inventory on close, not annotation.

## SW cleanup
- Only Embedding PID 52620 left; no taskkill; CloseDoc-only cleanup helper used between/after cells.

## OUT
- D:\工程\钣金导入\lxy_drawing_a2_6506153
- Docs: C:\Users\yue\Documents\lxy_drawing_a2_6506153 (accept/result/HANDOFF + per-cell SLDDRW copies)

## Do not claim
- Production / manufacturing drawing pass. Mode: explicit_partial_model_test. manufacturing_approved=false. Not pass_pending_visual (ownership fail before readback).