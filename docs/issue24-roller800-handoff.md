# Issue 24 — single roller overall length 800 mm

Developed independently from dev/cloud-ai at fecbdece1a96a35085cdde1a4b8de9c5acb8c804.
No edits to shared engine files or csharp-bridge/. No merge into dev/cloud-ai/main.

## Reuse and actual behavior

Existing RollerSpec carries overall_length_mm and generator math already subtracts
both shaft projections for barrel length. roller_spec's drawing conversion fills
missing wall/shaft/projection values with generic defaults, so existing-model
modification deliberately uses reviewed ParameterMapping/load_mappings instead.
It does not regenerate a customer roller from generic defaults.

`roller_variant.plan_variant(request)` computes:

    new barrel = 800 - preserved left projection - preserved right projection

Left/right projections are independent. The synthetic example is 1000 = 945+20+35
before, 800 = 745+20+35 after. These numbers are fixture data, not OEM dimensions.
The overall witness dimension and native axis bounds must both read 800 after
reopen. The planner rejects contradictory initial totals, impossible targets,
protected edits, cyclic dependencies and out-of-range changes. Missing dimensions,
interface inventory, dependency inventory or CAD mappings stay pending_mapping.

Declare dependent shaft lengths or mate distances with `dependencies` rows:
`parameter`, `depends_on` and optional `offset_mm`. The only formula is a sum plus
explicit offset. No arbitrary eval or implicit stretching of purchased parts.
Provide protected_parameters including shaft_diameter and the actual bearing,
shoulder and drive-interface dimensions; confirm and source both inventories.
No claim that a list of mapped dimensions proves every surface unchanged.

The Windows RollerDriver reuses NativeMachineDriver Pack-and-Go, owned document
handling, configuration switching, reference isolation, and sw_session/
owned_solidworks STA/PID/write guards. It reads mapped dimensions from copies,
plans against actual readback, writes configuration-specific dimensions only,
rebuilds/saves/closes/reopens, verifies mapped/protected dimensions, compares native
feature name/type inventories and mate status/static interference count, checks
axis bounds, and verifies source file hashes did not change. It records copied
artifact hashes/sizes and source hashes. No blanket CloseDoc/taskkill is added.

A part's axis envelope uses existing part_verification.solid_inventory. Assembly
bounds use component GetBox union, which is an approximate axis-aligned native
box, not exact topology or collision proof. The mapped axis must be aligned to
world X/Y/Z. The overall witness dimension is still required; unsupported oblique
rollers or ambiguous end reference mappings must be resolved by Gork. Motion and
mechanical/manufacturing approval remain unverified. Native signatures and COM
cleanup are not tested here.

## Callable workflow

```bash
python work/roller_variant.py plan --request examples/roller800-pending.json
python work/roller_variant.py package --request examples/roller800-synthetic.json --out runtime/roller800-handoff
```

Exit 3 denotes review/pending even for a ready offline fixture. Never use synthetic
fixture mappings as real SW targets. The package contains plan, request, pending
register, not-run Windows matrix and SHA256 HANDOFF, in gork-roller-800.zip.

Fill real source_document/configuration/axis and confirmed source/range-backed
mapping rows (`overall_length`, `barrel_length`, `left_projection`, `right_projection`,
protected and dependent dimensions). Inspect on Windows using only an owned session
and isolated copies, without dimension edits:

```powershell
python work/roller_variant.py inspect --request real-request.json --sw-exe <SLDWORKS.exe> --out runtime/roller-inspection-new
```

inspection.json contains the native measured request, plan and inventories. Keep
local paths private. Review the measured request and export it as a request JSON,
then run one isolated variant:

```powershell
python work/roller_variant.py native --request reviewed-measured-request.json --sw-exe <SLDWORKS.exe> --out runtime/roller800-native-new
```

API: plan_variant, execute_variant (injectable driver), export_package and
native.run_native(..., inspect_only=True/False). Existing project workbench shared
files are untouched; work/roller_variant.py is the dedicated callable CLI.
The native run always remeasures, so stale supplied measurement values are not
used to write copies. It currently does not cryptographically bind operator review
to a digest; confirm real mappings/configuration before invoking native execution.

## Unified test handoff and failure recovery

Seven focused fixture contracts pass; compilation and actual offline CLI package
creation pass. No comprehensive suite, Windows run or source CAD inspection was
performed. Real source dimensions, drive dependencies and bearing/shoulder maps
are not available in this cloud workspace, so OEM execution remains pending.

Gork: pin final PR commit, complete mappings; verify copied references never point
to originals; read overall/barrel/both heads before and after; confirm total 800
including both heads, unchanged shaft/fit/interface dimensions, intact editable
feature tree, successful rebuild/close/reopen, relevant mate status/interference
and separate process exit. Return checkpoint.json, inspection, source/output hashes,
feature/mate inventories, native errors and screenshots as one batch. Do not stop
existing p248 testing for each development module.

Each phase has atomic/fsynced checkpoint. Failures retain isolated files and logs;
uncertain cleanup is needs_review. No automatic retry, source overwrite or silent
acceptance. Rollback is to discard/archive the new isolated variant after operator
inspection and retain the untouched original; subsequent runs use a new directory.
The result is not a full model-history/geometry rollback transaction. Never delete
unknown sessions or use a saved file as evidence of clean process exit.
