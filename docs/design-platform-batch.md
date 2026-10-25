# Platform extension batch — code first, unified tests later

User scope: complete callable development before one unified test round. This
increment continues PR45, reuses ql5050px/sw_api/design_review and changes no
shared native engine, p248 geometry, COM owner or source CAD. It does not merge
unreviewed PR43/44 or silently switch a Windows test checkout.

## Callable capabilities

| Area | Actual implementation |
| --- | --- |
| Feature/parameter binding | mapping.suggest_bindings normalizes snapshots, reuses automatic_mapping, retains SI-kind ambiguity; approve_binding binds explicit role/range/source to unchanged report hash |
| Design intent/rules | existing design_review impact/protection plus rules.evaluate_rules for sourced unit-checked comparisons; confirmed binding roles feed the integrated review |
| Verification/correction | existing four-state evidence assessment and repair proposals; native.execute_reviewed_transaction binds exact plan/intent/mapping to the existing transaction, checks baseline/protected readback |
| Standard parts/mechanisms | catalogue validates sourced versioned entries, matches ratings/interface constraints, emits purchased BOM rows only after explicit selection confirmation |
| Calculation/selection | calculations delegates existing 8 calculation types and adds simply-supported central-load shaft deflection/stress, static cylinder push/pull and equal-load guide rating |
| Manufacturing | manufacturing reuses BOM/drawing planner and exports BOM CSV, drawing tasks, machining list and revision/material/per-job sheet input audit |
| Multi-model templates | templates instantiates structured parameter paths, protects interfaces, refuses range/unit errors, reports missing inputs and module configuration differences |
| Experience library | knowledge stores append-only SQLite cases with provenance, grade and hashed evidence; retrieval requires matching applicability context and always requires review |
| Project history/rollback | projects captures verified copied artifacts/parameters/code provenance in immutable revisions; restore goes only to a new directory and verifies hashes |
| Design assistant/workbench | bounded Chinese roller total-length parser; Tk mapping candidate table and sourced confirmation, request preview and unified package export |

Public modules live under src/design_platform/. Entry points are concrete
functions, not abstract stubs. Existing CAD feature recognition remains in its
current work line: name-based candidate matching does not establish complete
mechanical design intent or arbitrary topology semantics.

## One package entrypoint

```bash
python work/design_platform.py package examples/design-platform-batch.json --out runtime/platform-batch-new
python work/design_platform.py instruction '把这个滚筒总长度改成800 mm，轴径不变，两端安装结构不变。'
python work/design_platform.py gui
```

The synthetic example selects fixture parts, not real OEM/vendor models. Package
output: modules/*.json, platform-result.json, request.json, manufacturing/bom.csv,
drawing-tasks.json, machining-list.json, consistency report, HANDOFF.json and
windows-matrix.json in gork-platform-batch.zip. Source CAD binaries are excluded.
Requests can contain local paths; review packages before sharing. Each independent
module error is retained and remaining offline modules continue. Failed rules or
impact conflicts keep the aggregate failed; no output is manufacturing approval.

Additional CLI commands:

```bash
python work/design_platform.py approve-binding candidate-report.json approval.json --out confirmed-binding.json
python work/design_platform.py snapshot snapshot-specification.json --store local-project-history
python work/design_platform.py history --store local-project-history
python work/design_platform.py restore rev-<id> --store local-project-history --out new-restored-directory
python work/design_platform.py add-case case.json --database local-cases.sqlite --evidence-root local-evidence
python work/design_platform.py search-cases 'shaft' --context context.json --database local-cases.sqlite
```

Snapshot specification is {files:{portable_relative_name:local_source_file},
metadata:{project,source_revision,parameter_source,...},parent?:revision_name}.
Snapshots copy files locally only, never alter originals. Revisions check their
manifest digest and every captured file hash; restore refuses an existing output.
There is no in-place rewind of an open COM document.

Case schema requires title/source/source_revision/context/outcome/grade. Grades
are offline/native_reported/native_reviewed; native grades need local hashed
evidence, native_reviewed also needs a named reviewer. This records provenance,
not independent authentication of native evidence. Context filters must match;
retrieval never applies a repair or dimension automatically.

Binding approval requires parameter/document_id/dimension/role/source/reviewed,
current report_sha256 and adjustable allowed_range. Confirmed binding output
includes its approval_record and can be supplied back to binding_approvals in a
request; it is rechecked against the current snapshot candidate report. SI values
need explicit length/angle kind before conversion. No feature-name guess grants
native write authority.

## Native integration boundary

Within an existing proved owned/isolated STA host, supply its concrete transaction
port to execute_reviewed_transaction(plan, intentions, approval, mappings, port,
new_destination). It reuses sw_api.transaction.execute; it does not create an
application or attach to an arbitrary active one. Editable targets must equal
reviewed changes and their physical document/configuration/dimension binding.
Protected rows must be mapped, equal their measured baseline, and still equal it
after saved/reopened execution. The existing port preflight, writer, rollback and
source isolation remain mandatory. The plan must carry values_mm plus explicit
reviewed changes; generic incomplete requests are refused.

This facade is callable, but existing native commands have not been silently
rerouted through it. Gork/integration must supply the correct existing host port
and test the full call before treating it as the new production entrypoint.
Review SHA records alone do not create ownership, a model baseline or a native pass.

## Manufacturing and template rules

Catalogue source/revision/model/part number, installation interfaces and numeric
spec units are explicit. Catalogue data is user-supplied; this batch ships no
verified vendor database, CAD insert library or purchasing integration. Preliminary
calculations expose assumptions and never grant engineering approval. Guide moments,
shaft fatigue, cylinder buckling and continuous motion are outside these formulas.

Templates have id/revision/source, parameters, payload and bindings whose path is
a list of dict keys/list indexes. Missing values are pending. Manufacturing fields
thickness_mm/radius_mm/angle_degrees/k_factor in payload require a supplied per-job
binding; absent bindings clear those fields to None and mark confirmation pending.
No factory case is used as a per-job default. Module diffs identify changes, while
actual assembly propagation remains in existing assembly/drive planners.

Manufacturing output is linked planning data unless the existing native drawing
host is actually run. No fabricated datum, GD&T, process approval, or final flat
DXF is created offline. The module consistency audit covers declared rows and
metadata, not a new independent inspection of native drawing dimensions.

## Unified verification handoff

Per user instruction, no new unit/integration/regression suite or native execution
was run for this increment. Only compilation/import and a synthetic end-to-end
CLI package smoke, bounded instruction parse, local snapshot/restore and SQLite
record/search call smoke were performed. All Windows behavior and UI clicks remain
not_run. Earlier PR45's 15 checks apply to that earlier shared core, not this new
batch; do not count them as comprehensive tests of these modules.

Use delivery/design-platform/windows-matrix.json for one unified Gork/integration
round after the batch is accepted. Preserve real inputs, exact source commit,
component mappings, protected geometry inventories and per-job manufacturing data.
Issue39 COM reopen failures, Issue24 true roller validation and advanced feature
native signatures remain unresolved upstream dependencies; no claim they are fixed.
Ordinary issues discovered in the unified round should be logged against this
batch, keeping native failure and offline data contracts distinct.
