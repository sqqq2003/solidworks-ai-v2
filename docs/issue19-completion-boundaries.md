# Issue19 second delivery

New actual native definition adapters: hole/revolve/base flange/edge flange/sketched bend/relief. They require version-reviewed feature IDs, property maps, selections and sourced confirmation. This is callable CreateDefinition/CreateFeature execution, not automatic OEM mapping. Native parameter/property compatibility remains pending_windows_validation. Sketch arc creation now uses explicit center/start/end/direction.

Serial subprocess supervisor/worker adds per-attempt logs/PID/checkpoint, immutable request binding, failed-job retry in a new attempt, successful-job reuse and independent exit-code assessment. A timed-out worker is not killed; subsequent work refuses until its state is reviewed. A crash with a saved artifact is still needs_review, never unconditionally completed. No unknown SolidWorks process is terminated.

Public APIs: modeling_supervisor.supervise(jobs,root,resume=False,timeout=900); native_part_host.run_native_part; NativePartHost; sheet_feature_data.validate_extra. Native job JSON requires id/sw_exe/template/plan. Existing modeling_batch GUI/CLI remains the offline route; the supervisor is explicit Python API to avoid enabling native writes from unreviewed GUI requests.

Four offline mock contracts actually ran and are recorded in examples/offline-result.json. They validate dependency ordering only; not sketch geometry or native signatures. No full regression, Windows CAD, cleanup or process crash retest was performed.

Gork acceptance remains scoped: PR18 first generation/reopen/unfold evidence accepted, retest reopen/DXF not repeated, teardown crash unresolved. Windows acceptance matrix: all native feature-data maps; source geometry/dimension correspondence; p248 unchanged golden case; normal exit and 0xC0000005 isolation; timeout marker; retry preserving old attempts; persisted features after reopen; two-bend flat export. All pending_windows_validation.

Remaining engineering work: version-specific fixture validation, richer feature-value readback, automated native flat export for generic IR and OS-level crash dump analysis. This source delivery is not a claim of resolved COM crashes or certified manufacturing. Rollback by reverting this continuation commit; do not change p248 algorithm or original accept files.
