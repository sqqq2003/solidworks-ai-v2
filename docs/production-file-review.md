# Production input review and unified acceptance export

Adds callable development on top of product 426351b. Existing native feature
fixes and ownership guards remain unchanged. No CAD input or native binary is
committed by this increment.

## Local review, then explicit native execution

1. Generate the existing production package and resolve its OEM mapping.
2. On the machine holding the real files, seal the ready plan:

```powershell
python work/project.py review-production runtime/production-handoff/production-plan.json --out runtime/reviewed-production.json
```

Read the returned new review_sha256 and inspect the sealed plan. It contains
absolute local input paths, so keep it private. The command reads the declared
catalog source/template files, generation CAD paths and drawing/BOM/sheet-format
templates, and hashes their bytes in chunks. It also hashes the local QL modules
and named native/session dependencies. Pending plans cannot be sealed. It does
not start COM, infer engineering approval, or upload model files.

```powershell
python work/project.py native-production runtime/reviewed-production.json --sw-exe <SLDWORKS.exe> --output runtime/new-native-run --review-sha256 <new-reviewed-digest>
```

The CLI now requires a sealed plan. Changes to declared input inventory, file
bytes or recorded implementation invalidate the review. Inputs are rechecked
before execution and each stage. This is a point-in-time check, not a filesystem
lock. Hidden SLDASM dependencies are not discovered by this reader; native
Pack-and-Go/reference checks still apply. Preserve the pinned source commit.
Moving files or updating code requires a fresh local review.

Python: `seal_production_review(plan)`, `verify_production_inputs(plan)` and
`verify_production_inputs(plan, require_seal=True)` in `production_review`.
Legacy direct `execute_production` callers retain plan-only compatibility; their
checkpoint is explicitly legacy_unsealed, and the new audit reports unsealed_inputs.

## One whole-machine evidence ZIP

Pass the directory containing the production transaction's checkpoint, normally
`runtime/new-native-run/production`, not the outer owned-launch directory:

```powershell
python work/project.py export-production runtime/new-native-run/production --out runtime/new-production-evidence
```

Python: `audit_production(directory)` and
`export_production_acceptance(directory, new_destination)` in `production_acceptance`.

The audit requires returned assembly/drive/checks/drawings stages, completed
transaction status, a review digest and recorded input verification. It rehashes
recorded artifacts and checks every final model/drawing/flat-export receipt
against those artifacts. Missing receipts, tampered/external paths, incomplete
stages, absent native-check declaration or missing assembly/drawing/BOM output
classes prevent execution_evidence_complete. Failed checkpoints can still be
exported, with explicit evidence errors.

The ZIP contains production-acceptance.json and SHA256.json only: no CAD binaries,
raw checkpoint, raw logs, input paths or receipt absolute paths. Mechanical counts
are retained, including interference findings; zero count is not a mechanical
pass. execution_evidence_complete means reported-stage/file checks are complete,
not independent model inspection. Native acceptance, manufacturing approval and
external process-exit evidence remain unapproved/pending. The exporter cannot
certify a worker-supplied checkpoint or detect omitted artifacts independently.
Use alongside the separate local native logs and pinned test source.

## Focused verification and handoff

Six new offline integrity/export contracts plus five existing production-flow
contracts pass. Python compilation and CLI entrypoint checks pass. All artifacts
in checks are fixture bytes, not native CAD. No broad regression or Windows test
was run. Gork's next unified run should include review, input-change refusal,
unchanged-file execution, final-reference/configuration checks, native drawing
and flat output, artifact tamper detection, and separately observed process exit.
Unresolved native recipe type-mismatch/shaft disconnect validation from PR22 r2
remains governed by docs/pr22-r2-review.md; this change does not claim it solved.

Revert this increment to restore the earlier plan-only CLI behavior. Preserve
failed output directories and use a new destination for subsequent runs.
