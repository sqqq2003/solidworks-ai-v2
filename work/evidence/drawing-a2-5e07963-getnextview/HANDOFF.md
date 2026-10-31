# HANDOFF — A2 1:10 / 1:20 retest @ 5e07963 COM + c9d1b6b drawing

## Tips
- COM/owned: `5e07963b793d7cab9a743a9a014555c5ec60067e` (owned_document_lifetime / sw_owned_launch / solidworks_generator)
- Drawing: `c9d1b6b87b7ccfcd952b43c580bf4aa27f1b34de` (native_machine SaveAs title retarget) + annotation/com_access from `6506153`
- DESKTOP_REPO HEAD detached at 4344f22 with those overlays; blobs matched tip at deploy

## Cells (honest)
- **A2_1-10**: `failed` — DISP_E_MEMBERNOTFOUND (-2147352573) on `GetNextView` via `native_machine.read_member` after SaveAs (native_drawings.py ~179). SessionOwnershipError gone. SLDDRW written. No PDF/sheet_readback.
- **A2_1-20**: `failed` — (-2147352573, '找不到成员。', None, None)

## Owned / annotation
- SessionOwnershipError (unowned documents): **gone** on these cells
- GetAnnotation AttributeError / prior note MEMBERNOTFOUND: **not in traceback**
- New fail: **GetNextView MEMBERNOTFOUND** during post-save view walk

## SW cleanup
- CloseDoc-only; Embedding left alone

## OUT
- D:\工程\钣金导入\lxy_drawing_a2_5e07963
- Docs: C:\Users\yue\Documents\lxy_drawing_a2_5e07963

## Do not claim
- Production drawing pass. Mode: explicit_partial_model_test. manufacturing_approved=false.