# Gork review and Issue19 development slice

PR18 evidence at 6fe5a9f: reported step0 4/4 at e81438b with local VARIANT/warm-reuse patches; SW2022, operator-authorized warm PID (not proved exclusive). Requested bend indices 106–109 zero-based, selected profile 299 one-based. Initial r3 evidence reports reopened/rebuilt/unfold exported and bound-app closure. Retest reports 4/4 and inline unfold, but its own reopen/DXF skipped. Retest accept reconstructed after access violation. These distinct evidence levels must not be collapsed.

Accept generation/geometry evidence as reported; do not accept stable process exit or exact equivalence to clean e81438b. Local source patches/runner scripts and native binaries were not uploaded. PR17 bridge is independent and still Windows-unverified. No original accepts rewritten.

This slice adds NativePartHost: template creation, editable supported features, rebuild, feature readback, exclusive new save, close/reopen/readback. Reuses session/machine/feature code. Staged execution persists fsynced per-feature evidence and separates modeling, document cleanup, process exit. It cannot catch a native access violation inside Python; checkpoint survives only completed writes. Process exit remains externally observed, never inferred from artifact existence.

Offline modeling_batch serially validates mock feature dependencies and persists per-item results; resume binds identical job input. No fake native part is written. Failed-item retry uses a new output directory for now. Existing BatchRunner remains available for dependency workflows. Native queue orchestration/process-isolated worker supervision is not complete.

CLI/desktop action modeling_batch is offline. Native public API run_native_part(sw_exe,template,plan,new_output_dir) must execute in a separately supervised Windows Python process. Only owned docs are closed; no unknown SW process shutdown. No shared warm reuse shortcut was added.

Capability: native sketch line/circle, extrude/cut, mapped fillet/chamfer/mirror/pattern; arcs, revolve, hole wizard and native sheet builders remain pending. Existing dedicated sheet/turned generators are not replaced. Mock examples for four part families are contracts, not native success.

Gork matrix: original p248 4/4 golden configuration; unchanged transform/fixed face; save/reopen/unfold/geometry; COM return plus process exit independently; each supported editable feature; unsupported feature refusal; cleanup failure; batch resume/input-change rejection; no source overwrite. All new-code Windows checks pending. No full regression performed. Roll back this independent integration branch to its base; evidence PR18 is kept separate.
