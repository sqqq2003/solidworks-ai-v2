# Issue19 unified execution delivery

CLI offline: python work/project.py ql --action modeling_batch --config examples/modeling_batch.json --output-dir runtime/mock-new
CLI Windows native: python work/project.py native-parts reviewed-native-jobs.json --output runtime/native-new
Resume/retry: same native command plus --resume. Never change job input for an existing batch. Failures get new attempt directories; successful outputs require matching SHA256. Timeouts retain PID/logs and block continuation until explicitly reviewed. No Python/SW process kill.

Native jobs require id, sw_exe, template, plan. Plan features require id/kind/depends_on/confirmed/evidence/parameters. Base primitives use existing sketch/extrude/cut builders; other types use explicit reviewed native_feature_id/native_properties/references/mapping_source, never guessed OEM data. Arc direction is mandatory. Optional readback_dimensions [{name,unit,value}] compares native SystemValue before save and after reopen. flat_export=true requires base_flange and exports native DXF after reopen.

Native capabilities implemented but unverified: line/circle/arc, driving dimensions/relations, extrusion/cut, mapped hole/revolve/fillet/chamfer/mirror/pattern/base/edge flange/sketched bend/relief definitions. Unsupported property names or missing mappings reject before modeling. Feature existence/type and explicitly listed dimensions are read back; this is not complete mechanical validation.

Evidence lifecycle: model save checkpoint and artifact hash separate from CloseDoc result, native process exit and external supervisor result. Crash is needs_review even if saved. Pending process exit never becomes a passing accept automatically. p248 algorithm untouched; golden source equivalence still unverified due unuploaded local patches.

GUI remains offline modeling_batch route; native execution is deliberately explicit native-parts CLI. Full GUI native review form and OS crash-dump automation remain unimplemented; actual Windows signature, dimension naming, DXF and cleanup stability are pending_windows_validation. Four mock contract cases previously executed, not native examples. No claim of production-ready p248 exit or manufacturing approval.

Gork one-time matrix: four reviewed part families with real templates; each native feature; dimensions/readback; flat export; source isolation; crash-before-save vs crash-after-save; cleanup error; timeout and resume; failed retry and successful hash binding; p248 golden 4/4/reopen/unfold and process exit separately. All Windows cases untested. Revert continuation commit to roll back, keep original accept records.
