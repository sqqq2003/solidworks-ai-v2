# SolidWorks AI V2.0 — platform priorities and shared design review

This development order incorporates the user's platform direction on 2026-10-25.
It changes the sequencing and common contracts, not the meaning of native evidence.
Existing five delivery areas remain: QL parameter variants, controlled SolidWorks
execution, assembly/motion/interference, sheet metal, and drawings/BOM.

## Delivery sequence

1. Stabilize existing sheet-metal execution and COM lifecycle. Retain p248 bend
   success evidence separately from reopen, unfold and clean-exit evidence.
   Issue39's S2 disconnect is an unresolved native blocker, not an appearance pass.
2. Validate existing 3D model variants first, starting with Issue24 roller total
   length 800 mm including both shaft heads. Preserve shaft diameter, shoulders,
   retaining grooves, threads, bearing fits and reviewed installation relationships.
3. Extend 2D CAD to editable 3D using the existing analyzer and feature-tree work.
4. Expand mechanical rules, calculations, catalogue selection and native verification.
5. Extend whole-machine variants and assembly dependencies using existing QL trees.
6. Complete linked engineering drawings, BOM, unfold DXF and machining lists.
7. Multi-machine templates, traceable experience and the natural-language workbench.

The eight capability areas have these priorities:

| Priority | Area | Integration direction |
| --- | --- | --- |
| P0 | Feature recognition and parameter binding | Reuse intelligent_scan/automatic_mapping; candidates require sourced confirmation |
| P0 | Mechanical design rules | Reviewed protected/adjustable interfaces and dependencies; reject conflicts |
| P0 | Verification and corrective proposals | Rebuild/dimension/reference/mechanical/manufacturing evidence; no guessed correction |
| P1 | Standard parts and mechanisms | Extend sourced catalogues with installation dimensions and BOM identities |
| P1 | Mechanical calculations and selection | Reuse mechanical_selection; require actual loads/materials/duty inputs |
| P1 | Drawings and manufacturing output | Extend existing native_drawings/drawing_bom/sheet output |
| P2 | Multi-machine templates | Reuse modular QL tree and configuration dependencies |
| P2 | Experience knowledge | Versioned cases with failures, evidence and applicability; no blind reuse |

Previously accepted model-mapping wizard, standard-part selection, and project
version/rollback are retained. Traceable model/parameter/code/output identity and
isolated-copy recovery apply across these areas. Natural-language input generates
an explicit reviewable request; it must not silently authorize a CAD write.

## First callable shared implementation

New package `src/design_review/` reads existing planner/evidence dictionaries.
It adds no parallel solver, native session, COM activation or customer model.
Its initial adapters accept roller_variant `changes` or QL drive_variant
`component_modifications[].edits` without importing an unmerged roller branch.
This batch adds review interfaces; existing native entrypoints do not yet consume
these reports as a mandatory gate. Source/input hashes and ownership checks must
remain at their existing host boundaries.

`analyze_impact(plan, intentions)` produces changes, unchanged edits, protected
readbacks, transitive affected parameters/features/mates, risks and conflicts.
Intent roles are adjustable/interface/fixed/purchased/unknown. Reviewed units,
sources and allowed ranges are explicit. A feature-name hint is not confirmed
mechanical meaning; general automatic design-intent recognition remains future
work. Unknown dependencies/mappings remain review_required. A protected edit
fails the review. This does not geometrically prove the absence of a shoulder,
groove, thread or bearing face omitted from the confirmed inventory.

`record_approval(report, reviewer=..., review_sha256=...)` binds a named review
to the exact plan and intent hashes; changed reports cannot reuse approval.
The record alone grants no native write permission or input-file access.

`evaluate_acceptance(record, artifact_root=...)` checks submitted evidence for
roller/sheet/machine profiles. Every required result needs explicit native grading,
source, matching run ID and pinned 40-character source revision. It checks owned
session declaration, required output roles, contained nonempty artifact hashes
and actual reported process exit code. Dimensions/protected-interface/sheet-parameter
checks also require comparisons with explicit name/expected/actual/tolerance/unit;
a mismatched numeric readback fails even if the runner declares passed. No
tolerance is invented when it is absent. Not-applicable exemptions are restricted
to sourced/reviewed mates/interference/motion applicability; ownership or process
exit cannot be waived.

- passed: all required submitted checks and artifact integrity pass.
- degraded: required checks pass, optional checks fail or lack evidence.
- failed: required failure, nonzero observed exit or changed/missing declared artifact.
- review_required: missing/unverified/offline required evidence or incomplete mapping.

These states assess supplied evidence, not independent CAD execution or automatic
manufacturing release. A forged native label is not independently authenticated by
this offline module. Local native runner evidence and Codex/Gork review remain
necessary. A model file existing or looking correct never creates a pass.

`propose_repairs(assessment)` returns evidence-linked next actions for failed or
missing checks. It does not invent dimensions, fill t/R/K/angle defaults, suppress
rebuild errors, kill processes or execute a geometry correction. Future automatic
correction requires a reviewed whitelist, confirmed references and post-fix checks.

## Calls

```bash
python work/design_review.py --out runtime/impact.json impact --plan examples/roller-impact-plan.json --intent examples/roller-design-intent.json
python work/design_review.py --out runtime/assessment.json acceptance --evidence local-native-evidence.json --artifact-root local-native-output
python work/design_review.py --out runtime/repair-proposals.json repairs --assessment runtime/assessment.json
```

The impact example is explicitly synthetic and intentionally leaves dependent
shaft/support mappings pending. It creates a review report, never an executable
OEM plan. For evidence shape, see the focused fixture tests: profile, run_id,
source_revision, checks[{id,status,execution,evidence}], artifacts[{name,role,sha256}].
Evidence source fields are provenance records, not a cryptographic authentication.

15 focused offline contracts pass, Python compilation passes and the actual CLI
impact example returns review_required. Test fixture bytes/records are not CAD or
Windows evidence. No full regression or native test was performed. This branch
only adds the shared read-only implementation and development order; it does not
claim the eight platform modules or complete intent recognition are finished.
