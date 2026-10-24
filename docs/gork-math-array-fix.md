# Gork mathematical-array feedback

Source: Issue #5 latest comments. Native local oracle reports zero deviation only after using VARIANT(VT_ARRAY|VT_R8, tuple). Its local patch and evidence files are not uploaded, so this change independently implements that reported bridge, not a byte-for-byte import of Gork files.

sw_math_arrays provides finite/length validation, typed point/transform creation, transform readback and an independent native MultiplyTransform comparison using ArrayData. No .X/.Y reads and no IPartDoc.SketchManager access. The new work/run_transform_oracle.py runs only on the proved owned instance; it creates no CAD document and does not execute p248.

Run on Windows: python work/run_transform_oracle.py --sw-exe <installed executable>. Then Gork may resume existing step0-only procedure if the oracle succeeds. No deepening policy changed. Original generator currently does not call CreatePoint/CreateTransform, so no speculative coordinate algorithm or bend-geometry patch is applied.

Local Windows evidence remains unavailable here. Syntax only; native and regression tests not run. p248 remains unverified (last visible bend result 2/4), even if the math oracle passes.
