# Issue 15 development delivery

API: geometry, feature_plan, manufacturing_rules, diagnose, execute_part, run_cad_features in ql5050px.cad_features. Existing workflow/CLI/desktop add cad_features.

`python work/project.py ql --action cad_features --config examples/cad_features.json --output-dir runtime/cad-new`

Five callable areas are implemented as a first development slice. Geometry delegates actual CAD files to cad_analyzer; normalized fixtures preserve entities/layers and hole candidates. Feature IR orders supported editable features and rejects cycles/unconfirmed depth. Manufacturing rules emit sourced limits and advisory pending states. Diagnostic hypotheses never claim confirmed causes. Native execution reuses owned transaction ports and requires host create_editable_feature/verify_feature_tree implementations.

Known incomplete scope: robust inner/outer topology, dimension relation inference, block expansion, full collision checks, native per-feature COM builders and comprehensive manufacturing heuristics remain unfinished. The execution API is not a completed native modelling engine. Existing sheet/turned generators remain available separately. No claimed Windows results. Ambiguous depths and process data stay pending. This delivery does not claim the full Issue acceptance is met.

Gork matrix: CAD units/topology/blocks; IR cycles/evidence; missing depth/bend parameters; feature creation/rebuild/readback/reopen on Windows; relief/hole clearance/plant standards; diagnosis ranking; CLI/desktop and original-file isolation. ALL NOT RUN. Finish previous p248 first. No ordinary bug fixing or comprehensive regression performed.
