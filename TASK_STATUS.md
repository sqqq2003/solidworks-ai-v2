# 任务状态

## GORK-CLOUD-002

- 状态：**完成（模拟）**。Linux 上会话安全测试与发现阶段为 OK。见 `results/cloud/result.json`。
- 分支：`dev/cloud-ai`
- 范围：把云端可运行源码放到本仓库，并在 Linux 上跑模拟测试。
- 实机：不适用。`sw_live=not_applicable_on_linux`。云端不能声称 SolidWorks 已通过。
- 跳过（包里没有对应模块或基线文件，测试文件仍保留）：
  - `test_baseline_hashes_match_uploaded_sources`：没有 `results/cursor/baseline/src` 原件。
  - `tests/test_engineering_controls.py`：没有 `engineering_controls.py`。
  - `tests/test_workbench.py`：没有 `a01.py` / `data/machine_spec.json`。

## 另一条轨道（不在本次云端收口里）

- **A01-002B-1 rework2**：模拟测试 `simulated_pass`。
- SolidWorks **没有**实机测试。
- 等 Codex 另行复核。不要把这条和 GORK-CLOUD-002 的云端结果混成一次实机通过。


## CODEX-CLOUD-003

- Baseline: `1dabef3264eba142b811cafab3076181105c4994`; exact Git blob hashes verified before edits.
- Restored offline A01 parameter planner, engineering metadata gates and reviewed pure geometry tests. Missing modules now fail normally instead of being silently skipped.
- Fixed retry/result/progress contract, partial bend count, bounded contour search, converter timeout/return code, portable output path and serialized STA write gate. Native PID termination disabled until process-lifetime ownership is implemented.
- Regression evidence: `python work/run_cloud_tests.py`, `results/cloud/latest.json`. Counts include 4 independent boundary tests; cross-process marker lock is reported separately.
- 36 original feature-contract cases remain under `tests/pending_features/` because their algorithms/interfaces are absent (border relief 9; artifact/spur 5; dimension-driven turned parts 22). These are NOT passes. GUI tests requiring the absent desktop app are not cloud tests.
- A01-002B-1: simulated checks pass, **Windows/live gate remains review_required**. Spawn ownership bridge, process lifetime, native mate/rebuild and timeout recovery still need Windows evidence.
- A01-002B-2: result status groundwork implemented (`degraded`, `unverified_existing`, CLI exit 3). Content-bound resumable artifact manifest implemented with source/parameter/code/output hashes, atomic metadata and invalidation tests. Existing nonempty files alone are not accepted.
- A01 foundation: 1800×900×1500 target retained; unknown measured dimensions remain null; register captures units, source, dependencies, range and confirmation. CAD release remains false.
- No customer CAD or original D-drive data changed; no external AI task duplicated.

## GORK-CLOUD-003

- Remote baseline unchanged: `850c3c3e516d1048f723c8a9b5f1220fa4db4098`; dependency environment reused and checked. Baseline: 275 pass, 0 failures/errors, 4 skips.
- Reproduced two stale-cache subtest failures (edited profiles and bend lines) and one resumed-result callback error. Resume now fingerprints every geometry collection consumed by generation. Observer errors no longer abort a resumed batch.
- A01-002B-1 remains simulated-pass / Windows-review-required. Native PID termination stays disabled; exclusive spawn/lifetime ownership and actual recovery remain unverified.
- A01-002B-2 portable resume hardening implemented; targeted tests: 29 passed / 1 explicit baseline skip; full regression: 277 passed, 0 failures/errors, 4 skips; cross-process lock passed.
- No Codex Cloud environment-administration tool is available. Minimal manual commands are in docs/codex-cloud-env.md; real Ubuntu CI remains the Linux verification route.
- 36 absent feature-contract cases remain separately documented, not counted as passes. No original CAD touched.

## GORK-A01-004

- 状态：**云端模拟可跑**。`python -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run` 写出尺寸计划并走 mock SolidWorks 适配器。
- 实机：分开。`sw_live=not_applicable_on_linux`。Windows `--live` 只在用户电脑（DDD）上、并且 `sw_session.require_model_write` 证明独占会话之后才允许 SaveAs 到另一份工作副本。本次没有实机通过。
- 未映射（pending_mapping，不填 OEM 数）：`A01.conveyor.passline_height`、`A01.conveyor.roller_pitch`、`A01.conveyor.roller_count`、`A01.drive.center_along_length`、`A01.drive.chain_pitch`、`A01.drive.sprocket_teeth`、`A01.drive.bearing_journal`、`A01.mount.motor_x`、`A01.mount.motor_z`、`A01.mount.bearing_span`、`A01.interfaces.sheet_thickness`、`A01.interfaces.thread_major_diameter`。
- 下一轨只搭了骨架，不是完工功能：装配配合检查（mock，不求解）、钣金钩子（调用已有 `generate_sheet_metal`，默认不执行）、工程图导出（对齐 `roller_drawing` / `drawing_notes` / `roller_spec`，不写文件）。
- 证据：`python work/run_cloud_tests.py` → `results/cloud/latest.json`。`tests/pending_features/` 仍不算通过。
