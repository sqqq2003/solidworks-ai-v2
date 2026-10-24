# Issue19 unified source delivery

This supersedes earlier partial delivery notes. Code completion means callable implementations and one reviewable package; Windows correctness, process stability and manufacturing acceptance are still pending_windows_validation.

## One version / dependency boundary

Work on PR20 only, baseline 4b81e2b. PR16 feature adapters and PR17 math bridge were selected into this branch earlier; they remain unverified implementations, not equivalents of Gork's local patches. PR18 is evidence, not executable source. The exact final source SHA is recorded in PR20/Issue19 delivery comment; source overlay hashes bind all files. Use the GitHub source archive for that SHA for a complete clean checkout. No customer CAD is bundled.

## Four complete recipe paths

`examples/production_recipes.json` contains explicit synthetic dimensions, source labels and confirmed fixture intent:

- Plate: rectangular sketch, solid extrusion, two circles, editable cuts; independent envelope/body-count readback.
- Bracket: closed L-section, extrusion, two explicitly positioned holes; envelope/body-count readback.
- Shaft: closed stepped half-profile, existing turned generator, save/reopen and independent length/diameter readback.
- Sheet: rectangular blank, red BEND layer with two explicit bend positions; existing analyzer, confirmed P0 plan, unchanged bounded-relief generator, reopened sheet data, folded/flat evidence and native DXF. Recipe direction/K/radius/thickness are explicit. It refuses if analyzer does not find exactly two bends.

These are synthetic fixtures, not QL OEM dimensions. Advanced generic feature-data operations still require version-reviewed native IDs/properties/selection references. Capability matrix distinguishes direct builders, existing engine delegation and mapped operations. No unsupported kind is silently converted to an imported body.

## Commands

```
python work/project.py ql --action modeling_delivery --config examples/production_recipes.json --output-dir runtime/modeling-delivery-new
python work/prepare_modeling_delivery.py examples/production_recipes.json --out runtime/modeling-package-new
python work/project.py review-parts examples/production_recipes.json --sw-exe <installed SLDWORKS.exe> --template <reviewed .prtdot> --sketch-plane <actual template plane name> --out reviewed-native-jobs.json
python work/project.py native-parts reviewed-native-jobs.json --output runtime/native-batch-new
python work/project.py native-parts reviewed-native-jobs.json --output runtime/native-batch-new --resume
python work/project.py recover-parts <attempt-directory> --reviewer <operator> --evidence <SW-session-review-record>
python app.py
```

`review-parts` is a deliberate operator review command, not an automatic engineering approval. The reviewed digest binds recipe/bindings; template SHA rejects post-review changes. GUI button “审核并运行原生配方” provides the same review, preview, confirmation and resume workflow. It shares the workbench busy/stop state and runs no SW unless explicitly confirmed. Stop waits for the current worker; it does not kill SW.

Native execution is Windows-only. `--resume` preserves prior attempts and retries failures into new directories; successes require original input signature and artifact hashes, including part/DXF files. Abnormal native exit or unresolved cleanup stops further workers. Timeout leaves the worker alive and prevents overlapping writes. `recover-parts` only records review after proving the old Python worker exited; it does not close/kill any SW process. Operator must separately inspect the previous SW session.

## Lifecycle and crash boundary

Each feature records source evidence and rebuild result. Durable checkpoints are written atomically before risky document closure, not only at final return. Save, reopened readback, flat export, owned CloseDoc and external Python exit have separate states. faulthandler stderr and per-attempt PID/exit-class support access-violation investigation. A saved file plus EXIT=139/0xC0000005 is needs_review, never unconditional success. Native-part source/control code does not change the p248 bend algorithm, fixed-face policy or original accept files.

Process isolation is a recovery mechanism, not a proved fix for OLEAUT32/COM crashes. Automatic Windows dump analysis is not implemented. Gork may attach OS crash evidence to the existing stage/log package; COM reference-release behavior and native typelib signatures require Windows validation.

## Actual checks in this batch

- Combined source AST and selected engine/host/worker/GUI import checks, no COM started.
- Unified project CLI generated four dimension-complete offline recipe plans and one checksum package (exit 3 = review required, expected).
- Initial synthetic sheet DXF had an uncolored BEND layer and produced zero bends; new recipe emits the existing parser's supported red bend layer. The unchanged analyzer then found two bends and existing sheet mock pipeline returned simulated_pass.
- Additional focused boundary checks and generated reports are included in delivery/issue19-unified. No full regression, native feature generation, GUI click, original p248 or Windows teardown retest was run. Offline pass never means native pass.

## Gork once-only Windows matrix

1. Original Gork p248 golden recipe and local patch provenance: 4/4, saved rebuild/reopen, unfolded DXF, geometry and process exit separately. Never infer source equivalence to clean e81438b.
2. Four reviewed recipes: actual template/plane naming, editable feature types, hole direction, shaft profile, exact two bends and relief path, dimensions/body count after reopen, DXF opening.
3. Generic mapped fillet/chamfer/mirror/pattern/hole/revolve/sheet definitions: reviewed enum and property binding, invalid selection refusal and native result readback.
4. Batch/GUI: preview and stale-review refusal, retry after safe failure, successful hash reuse, changed input/template/part/DXF refusal, no concurrent native writes.
5. Lifecycle: failed rebuild, save error, CloseDoc identity failure, worker crash after save, timeout, explicit recovery review; no original overwrite or unknown process exit/kill.

All Windows rows pending_windows_validation. Geometry tests do not certify fatigue, load, manufacturing tolerances or process approval. Generic feature plans must include native mappings; absence is a hard refusal, not an invisible fallback. Full arbitrary CAD semantic reconstruction remains outside these explicit recipe fixtures.

Rollback: revert this continuation on PR20 or check out its parent; keep golden evidence and previous attempt directories. Do not delete failed native outputs before preserving logs. No production/GT-ZX mapping data is changed.

Evidence gate: `python work/project.py golden-check <accept.json> --verification <r3.json>` compares golden inputs and keeps generation/reopen/process/source-equivalence evidence separate. It never rewrites accepts or infers a new pass from old binaries.

CAD/IR bridge: `python work/project.py plan-cad input.dxf --features reviewed-feature-request.json --out cad-plan.json` reuses PR16 geometry/feature planning. It records source SHA; native host rejects changed source. Feature evidence/depth must be explicitly reviewed rather than inferred from ambiguous drawings. The plan field can be supplied to the existing native job manifest. QL action cad_features remains available alongside the recipe routes.
