# Editable operation continuation

EditableFeaturesMixin now supports sketch/extrude/cut plus fillet/chamfer/mirror/pattern through actual FeatureManager.CreateDefinition/CreateFeature calls. It inherits mapped selection, constraints and dimension operations. feature_plan execution validates all operation mappings before acquiring the writer or changing the model.

Parameters for advanced operations: mapping_confirmed=true, mapping_source (review record and SW version), native_feature_id (confirmed native enum), references [{name,type,mark}], native_properties {property:{value,unit}}. Supported properties are deliberately allowlisted in feature_operations.py. Native IDs are not hardcoded or guessed. Invalid units/properties/missing selections reject execution. Native property names/selection marks must be reviewed against the deployed typelib; these calls remain untested.

Sketch constraints: parameters.constraints [{kind,confirmed,source,references,...}]. Supported horizontal/vertical/coincident/concentric/parallel/perpendicular/equal/tangent relations and dimension. Dimension uses value/unit and position_mm xyz, creates a driving dimension, checks SetSystemValue3 result and reads back SystemValue. This does not yet inspect native constraint status codes for overdefinition; failures require rollback and native review.

Host still supplies guard/model/writer/checkpoint/restore/save/reopen. This change does not attach unknown SW sessions or create a production-ready host. Native sheet-metal advanced builders, full geometric semantics, GD&T and manufacturing approval remain incomplete. New mappings must come from engineer-reviewed fixtures, never OEM guesses.

Gork matrix additions: missing/invalid mapping refused before any write; dimensional unit conversion; negative/zero feature dimensions; relation overdefinition; fillet/chamfer reference failures; mirror plane and array direction marks; save/reopen feature identity and rollback. All UNTESTED. Only AST syntax checks performed; no full regression or native calls.
