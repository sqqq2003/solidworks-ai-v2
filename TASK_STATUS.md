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


## CODEX-A01-005

- 云端工程接口与 mock 合约已实现；Windows 实机和机械验收仍待证据，不收口为实机通过。
- 基线 `43ce35fcfc5bdb8f81ea1d660fa48a68d832dbfc`：298 ran / 294 passed / 4 skipped；复用已有源码、依赖与参数图。
- 参数映射 v1：文档、配置、特征/尺寸、单位、依赖、来源、范围、固定/采购件和 pending 状态；CLI 可导出全 pending 模板。
- 新增事务 ExecutionPort、Windows 单写者桥接、内存 mock：preflight/diff/checkpoint/write/rebuild/readback/save-as/reopen/readback；失败恢复与幂等性，恢复失败明确 recovery_required。
- 禁用旧方程直写 live 路径。Windows 驱动需按 docs/a01-parametric.md 实现并绑定源模型后，以 apply_live Python API 接入。当前 CLI live 不具备实机执行条件。
- `python work/run_cloud_tests.py`：309 ran / 305 passed / 0 failures / 0 errors / 4 skipped，跨进程锁通过；新增 11 项测试（含多阶段故障注入子测试）。跳过原因仍为 DWG/LibreDWG/原始基线文件缺失。36 pending_features 不计通过。
- `python -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run --mapping-template runtime/a01-mapping.json` 可运行；12 项未知 OEM 映射保留，机械检查 unverified，cad_release_approved=false。
- 等待 Gork 的真实映射及 Windows 驱动/重建/保存重开读回/失败恢复/机械检查证据。本节写下时还没有 SolidWorks 实机通过声明。其后只增加了包络方程读回，见下一节，不是全面改型完成。

## GORK-A01-005

- 状态：**sw_live_envelope_verified**。用户电脑（SW Premium 2025 SP1.2 / Rev 33.1.2）核实了工作副本上包络全局变量 Length/Width/Height 的方程文本和 `EquationMgr.Value` 读回。不是全面改型完成，不是配合/干涉/运动验收，也不是 Linux 云端测试的结论。
- 母体：`GT-ZX-1300x000x750-001x1.SLDASM`，目录 `D:\工程\滚筒工程\滚筒\斜\斜滚筒线（120W电机） 标准\斜滚筒线-1300x000x750-方向A\装配图\`。不是 QL-5050。磁盘基准 Length=1300、Width=600、Height=750、FootHeight=50。原工程未覆盖。只读 13 个方程，关闭未保存。正文在 `results/windows/readonly_equation_dump.json`。
- 工作副本：`C:\Users\yue\A01-live-work\A01-1800x900x1500-v2.SLDASM`。`EquationMgr.Value` 读回 Length=1800、Width=900、Height=1500（`envelope_match=true`），FootHeight=50。证据：`results/windows/live_reshape_verified.json`、`results/windows/live_reshape_summary.json`、`results/windows/a01_parameter_mapping.json`。
- 方程写入：本机 `Equation` PROPERTYPUT 为 no-op。有效做法是 `Delete(index)` 后 `Add2(same_index, equation, solve=False)`。Delete 之后若仍有引用，`Add(-1)` / `Add3(-1)` 返回 -1 且变量丢失。脏会话 Close 不存盘可从磁盘恢复。用户电脑上 `D:\工程\改机工具\apply_variant.py` 的 `_equation_put` 已有该回退；该补丁不在本仓库，本提交没有把它合进客户路径。仓库适配器只在未接入的助手函数里记下同一写法，`apply_live` 仍要求 schema v1 映射和事务驱动。
- 未宣称：配合 / 干涉 / 运动未单独认证。DeckHeight、RollerLong 的 `Value()` 在工作副本上读回 -50 / 100，方程文本正确，不当成尺寸已解算。工作副本仍引用母体零件，归档需 Pack and Go。10 个 pending_mapping 仍 pending（传动、滚筒间距等）。板厚 2.0 只是零件名推断，`production_approved=false`，未写入求解器。
- 仓库不包含 SLDASM/SLDPRT。说明：`docs/a01-windows-live.md`、`docs/a01-parametric.md`。Issue #2 不关闭。
- Linux 模拟与这次实机分开。`results/cloud/latest.json` 的 `sw_live` 仍是 `not_applicable_on_linux`。云端测试通过不是 `sw_live_envelope_verified`。

## CODEX-A01-005：Gork 几何未更新反馈修复

- 基线 `41a4c99`，保留 Gork 原始证据。D1≈1001、DeckHeight=-50、RollerLong=100 尚未被实机修复确认；全局变量匹配不代表几何包络通过。
- 新增 equation_health 只读诊断，报告前向引用、公式推导/读回差异、实际尺寸验证状态；不执行任意公式代码，不把 Python 推导当作机械证据。
- 新增 solve_owned_work_copy：要求 Windows 独占任务 STA；拒绝共享/未知引用；启用 AutomaticSolveOrder，EvaluateAll，ForceRebuild3(False)，并读取真实 Parameter.SystemValue。求解错误、未定位尺寸、几何不跟随均保持失败。函数不保存。
- 加固 Delete+Add2：全部更新先验证，禁止覆盖派生公式，检查 Delete/Add2 返回值、方程数量及文本读回。
- 10 项新增模拟测试覆盖 Gork 数据、显式求解、几何不跟随、原生求解失败、共享引用与未知依赖阻断、删除失败、无效输入及公式循环。
- `python work/run_cloud_tests.py`：319 ran / 315 passed / 4 skipped / 0 failures / 0 errors，跨进程锁通过。36 pending_features 未计通过。
- Windows 操作和调用方式见 docs/a01-windows-live.md。待本机 Pack and Go、独占会话调用、实际尺寸及保存重开读回；未宣称根因已实机确认或模型已修好。
