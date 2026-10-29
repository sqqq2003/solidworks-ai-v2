# PR21 acceptance review and SW2022 interface fix

Evidence PR21 head 5d45af7 pins e1a14a7, not the later 58a2e34 unified delivery. Qoder and WorkBuddy independently report four mock jobs, identical-input resume and changed-input rejection. Accept those as offline evidence for the pinned version only.

Native official acceptance remains pending_windows_validation. The owned-spawn attempt could not bind the spawned PID to the COM object on the single-instance host; the write-gate refusal is correct. The warm harness created and read back a minimal circular extrusion, but bypassed require_model_write, so it is diagnostic evidence, not an accepted product write path. p248 was not run. Do not infer that COM teardown crashes are fixed.

The uploaded diff identifies two concrete SW2022 interface failures. Adapted onto current PR20 without reverting newer code: name the open sketch using FeatureByPositionReverse(0), wrap as IFeature and refuse a non-sketch result; find persisted features through typed IPartDoc.FeatureByName and wrap each result as IFeature. Never change session ownership checks or authorize arbitrary warm writes.

Four focused fake-interface regressions passed locally: no ISketch.GetFeature dependency, no IModelDoc2.FeatureByName dependency, missing feature rejection and non-sketch rename refusal. No COM loaded. New Windows validation remains pending. The local original native part, full harness and additional native logs referenced by the report were not included as product source.

Retest one new pinned product SHA in a legitimately proved owned session. Verify sketch/extrusion, cut and the four full recipes separately; preserve generation/readback/cleanup/process outcomes. If the host cannot provide owned COM identity, report environment_blocked instead of bypassing guards. No unknown SW process shutdown is authorized.

The previous unified ZIP is an immutable 58a2e34-era snapshot; use the current commit source archive or the accompanying PR21 patch bundle on that source. This revision does not claim current unified recipes were validated by the older e1a14a7 test packet.
