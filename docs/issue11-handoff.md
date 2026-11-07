# Issue #11 unified handoff

Four development modules: intelligent_scan (readonly Windows scan and offline incremental database/classification); automatic_mapping (ranked candidates and explicit approval boundary); intelligent_decision (protected part actions and rollback plans); mechanical_selection (speed/ratio/belt/chain/shaft-load/shaft-diameter/bearing-life/motor calculations and local JSON/CSV catalogue).

Public APIs: scan_snapshot, ReadOnlyScanner.scan, map_parameters, confirmed_targets, decide, calculate, select_catalogue, run_intelligence. Existing project.py/app.py and QL batch add action intelligence; this branch builds on Issue #9, which remains an unmerged dependency.

```
python work/project.py ql --action intelligence --config examples/ql5050px_intelligence.json --output-dir runtime/intelligence-new
```

Snapshot paths are fixture identifiers only. Nothing writes source CAD. Native scanner requires an already proved owned Windows app and lease. A host detail_reader can augment native mates/geometry/units; the built-in dimensions retain SI rather than guessing length versus angle. Unresolved SI dimensions cannot be approved automatically. Classification is keyword evidence at conservative confidence, not a trained model or confirmed machine recognition.

Known limitations: scan API/COM bindings, hidden/suppressed reference inventory and material/property return shapes need Windows validation; incremental updates require a complete input snapshot, not a partial delta. Candidate geometry/equation/mate evidence is retained, but full geometric semantic inference and equation solving are not implemented. Native dimensions/features and duplicate ambiguity remain manual review. Decision plans deliberately do not directly write models; use existing controlled assembly/drive APIs after mapping review. No global scaling. Local rules and derived order require engineer approval; complete kinematic dependency solving is still provided separately by drive_variant, not inferred from arbitrary OEM equations.

Calculations require positive finite sourced inputs with explicit units. Shaft model is solid circular maximum-shear preliminary sizing; bearing life uses user-provided exponent and equivalent load; motor sizing uses steady-state force/speed and explicit efficiency/safety. Fatigue, shock, startup, keyways, duty cycle, lubrication, thermal and manufacturer-specific load limits are not certified. No catalogue means no model selection, never invented vendor specifications.

All tests, regressions, native scanning and engineering validation NOT RUN. Only syntax/import checks and generation of the handoff artifacts are allowed in this batch. The generated JSON database, candidate map, decisions, calculations, missing-input states, checksums and one Gork matrix are in gork-intelligence.zip. Gork finishes old p248/GT-ZX before this batch. Source commit is recorded in the GitHub delivery comment; source overlay manifest binds exact file hashes to the baseline.
