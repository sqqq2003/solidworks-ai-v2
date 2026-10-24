# QL-5050PX linked manufacturing execution

This increment extends existing Issue 9 modules on PR 20, based on commit
367297751a9bc0add008c6b92a6e30a5c6d41ac9. No original CAD or binaries are included.

## Entry points

Create the offline package from the CLI, desktop `production_package` action, or
existing project batch jobs (`kind: ql5050px`, `action: production_package`):

```bash
python work/project.py ql --action production_package --config examples/ql5050px_production.json --output-dir runtime/production-handoff
```

The example reuses the synthetic Issue 9 parameter/drive specification. Its OEM
mapping remains pending, so it creates actual JSON/CSV/ZIP deliverables but cannot
execute native CAD. Never treat the target envelope as confirmed OEM geometry.

With a completely mapped configuration, inspect `production-plan.json` and its
`review_sha256`, then explicitly launch the owned Windows transaction:

```powershell
python work/project.py native-production runtime/reviewed-production.json --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --output runtime/new-native-run --review-sha256 <reviewed-plan-hash>
```

Before native CLI execution, run the new `review-production` step described in
[production-file-review.md](production-file-review.md). It binds declared local
source/template bytes and implementation hashes to a new review digest. The CLI
requires this sealed plan. Hidden assembly dependencies still require the native
Pack-and-Go reference audit. The native command rejects changed digests, incomplete plans, conflicts
and non-Windows execution. All existing owned-session/write guards remain active.
The desktop action exports plans only; it never silently starts native CAD.

Python callers use `plan_production(config)`,
`write_production_package(config, new_directory)` and, within the guarded driver
session, `execute_production(plan, driver, new_directory, review_sha256=...)`.
`run_owned_native(..., 'production', {'plan': plan, 'review_sha256': digest})`
provides the existing owned STA host boundary.

## Data continuity

Add explicit catalog-node bindings to the existing machine configuration:

```json
{
  "production_links": {
    "components": {"drive-component-id": "assembly-catalog-node"},
    "mates": {"affected-mate-id": "assembly-owner-node"}
  },
  "motion_samples": [{"dimension": "mapped-motion-dimension", "values_si": [0.0, 0.01]}]
}
```

Identifiers above are schema examples, not real OEM references. Each changed
component and affected mate needs its explicit binding; configurations must match.
The transaction builds the assembly, redirects drive edits to those built files,
then uses the drive operation's actual isolated dependency map for **all drawing
models**, including unchanged parts. Checks run against the final variant root.
Native model views select the receipt's configuration; BOM CSV uses the existing
assembly-tree explosion and grouping logic. Native SLDDRW, linked BOM/balloons,
part views and sheet flat DXF reuse the existing manufacturing driver.

Every stage writes an atomic/fsynced checkpoint before and after its call. A stage
failure stops dependent work, retains diagnostic files and never retries native
writes automatically. Missing variant dependencies or paths outside the transaction
are rejected. Successful return means outputs created and review required; it is
not mechanical approval, continuous collision proof, or proof of clean COM exit.
Native checks retain their findings without inventing a pass. Hashes cover model,
drawing, DXF and BOM output files. The whole-machine result has its own schema;
the part-batch `export-acceptance` command does not consume it.

## Unified Gork handoff

Pin the final PR 20 SHA from its delivery comment. Use the package's plan digest,
HANDOFF file hashes, pending register and not-run Windows matrix. Confirm all OEM
references/materials/process/datum/tolerance data before executing. Test assembly
isolation and configurations, linked drive dimensions and protected purchased
parts, saved/reopened final references, mate/interference/motion evidence, native
SLDDRW views/linked BOM/balloons, sheet flat DXF, and clean process exit. Keep the
original source files unchanged. Return the production checkpoint, output hashes,
version pin and separate process-lifecycle evidence once for the whole batch.

Five focused offline contracts pass: stage ordering and final-variant drawing
references; fatal drive stop/checkpoint; changed review refusal; pending plan
refusal; callable unmapped example package. Python syntax checks also pass.
Fixtures are fake bytes, not CAD. No broad tests, ordinary bug cleanup or Windows
COM tests were performed. Native API signatures, drawing semantics and COM exit
remain pending Windows validation. Existing templates, OEM source assemblies and
complete engineering mapping are required inputs, not supplied by this batch.

Rollback: use parent commit 3672977 or revert this increment; retain failed output
directories for diagnosis and choose a new output directory for subsequent runs.
