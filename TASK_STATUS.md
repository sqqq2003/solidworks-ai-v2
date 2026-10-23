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

## P0-CODEX-001：Issue #4 二维 CAD → 原生可编辑钣金首轮云端交付

- 新最高优先级为 #4，Gork 实机联调 #5；整机改型降为 P3。本轮复用已有分析/拓扑/轮廓修复/折弯计算/原生生成器与展开导出，未重做几何引擎。
- 新增 sheet_metal_pipeline：来源/解析几何/代码指纹，轮廓/孔/折弯特征计划，明确参数/方向/单位/折弯分类确认；未知保持 pending。支持首轮同角度绘制折弯，复杂混合角度/岛屿不猜测。
- 新增 WindowsSheetMetalPort：调用既有原生生成器、关闭后重开、检查原生特征树和可访问特征定义、t/R/K、折弯完成数，再展开导出并检查 DXF；参考草图或参数读回不符不能通过。
- 产物 staging、失败清理/独立诊断、恢复失败显式状态、跨进程发布锁、内容校验幂等。mock 永远只有 JSON trace，不产生伪 CAD。
- 修复 pywin32 将无参数 EditRebuild3 暴露为属性导致 bool 不可调用的问题；展开导出拒绝覆盖已有目标。新增 close_saved_document 选项保证重开检查使用磁盘文件。
- t=2.5/R=1、释放槽规则、折弯中心失败清理、K 对固定毛坯/固定折后外尺寸的差异均有回归；不能仅因固定毛坯展开长度不变就认定 K 未生效。
- `python work/run_cloud_tests.py`：333 ran / 329 passed / 4 skipped / 0 failures / 0 errors，跨进程锁通过；14 项新增算法/mock/Windows 接口合约测试。36 pending_features 仍不计通过。
- `python examples/sheet_metal_dry_run.py`：synthetic 二维板件→计划→JSON trace 通过；`work/run_sheet_metal.py` 提供本地 CAD 计划/dry-run/Windows live 入口。联调说明见 docs/p0-sheet-metal.md。
- 当前没有这次验收的真实钣金源样例与 Windows SW 执行环境；首轮真实 SLDPRT/可编辑/保存重开/展开/DXF 测量尚未验收。sw_live_verified=false（本次云端证据），不关闭 #4/#5。
- 开发期间收到 Gork 新提交 c6e00d8/b0c4dec：p190/p209/p243 报告本机原生钣金特征、重建、展开和 DXF 成功，保留全部原始记录。这些已有实机进展与本次新适配器测试分开；t/R/K 原生读回和明确关闭后重开证据仍待补齐。

## P0-CODEX-002：Gork K 因子与 p248 重试反馈修复

- 基线 b1319a0（含 Gork 后续 K 已读回匹配的证据），完整保留 Gork 原始 blocked/partial 证据。已读取 #4/#5 最新反馈：创建时补偿对象未接线、读回 K=0.31、部分折弯回退吞掉加深重试。
- 原 sw_tool_cli 新增 --k-factor，经 BendAllowanceSpec 传入 BaseFlange/BaseFlange2 与 InsertSheetMetal3dBend。长度 BD/BA 转 m，K 无量纲；显式补偿无法构造时不静默使用默认值。
- 创建对象先转为类型库 ICustomBendAllowance；重建后及保存前读回原生补偿类型和值。ModifyDefinition=True 不代表验证通过，K 不匹配不得保存或发成功事件。真实 COM 访问冲突是否解除仍需 Windows 证据。
- 最终部分折弯改为 BendRejectedError，保留 completed_bend_count，外层关闭本次未保存工作文档后从原图执行有界 +1.0/+1.5mm 重试；耗尽时旧 CLI 明确 degraded/exit3，原生发布管线仍拒绝。
- Windows 管线接入已有释放槽重试封装；修正多条折弯合并为一个 SM3dBend 的验收，使用完整完成条数及原生特征存在/重开重建，不把一条特征错当只完成一条折弯。
- 新增 10 项模拟回归，更新旧部分折弯测试为“上抛且保留真实完成数”。`python work/run_cloud_tests.py`：343 ran / 339 passed / 4 skipped / 0 failures / 0 errors，跨进程锁通过；36 pending_features 仍不计通过。
- 复测命令与读回字段见 docs/p0-sheet-metal.md。真实 p209 的 K 0.25/0.5、p248 加深、矩形内孔释放槽样本仍待本机核对；本轮没有新 SW 实机通过声明，也未覆盖用户 D 盘程序。
- Gork 在提交期间补交 b1319a0：本机补丁 K 已读回 0.5/0.25，但固定源毛坯 DXF bbox 相同。本轮保留该证据，新增 audit_k_factor_evidence，未确认尺寸基准时 pending；fixed_blank 假设下仅为 consistent_fixed_blank_pending_folded_measurements，不能断言 SW 忽略 K。
- Windows 重开诊断新增折叠/展平实体 bbox 测量并恢复 FlatPattern 原状态，不保存；任一步失败不得继续导出。等待两组 K 的折叠尺寸/真实展平实体/DXF 对照，不把同 bbox 或公式差当作最终机械结论。

## P0-CODEX-003：独占启动入口与 p248 重试证据

- 基线 f563120；Gork 最新复测 K 写入和重开读回已匹配，固定毛坯展开不变、折后 Z 差异约 0.98mm；继续区分尺寸基准。该轮临时 attach shim 不能当成正式会话验收。
- 新增 sw_owned_launch：显式指定 EXE，真实 Popen 启动，保留 Windows 进程句柄核对 image/生存期，匹配 COM GetProcessID，完整空文档清单后才 claim_spawned_process。错误进程、转发/退出、枚举失败、外来文档均拒绝写入。
- 正式会话在每次写入前复核，复用已绑定对象；中间生成/重开/导出不退出实例，最终只在空且归属有效时 ExitApp，无强杀。保留 cleanup_status 和失败 PID 诊断，不接管已有活动实例。
- CLI 与 work/run_sheet_metal.py 新增 --sw-exe；work/probe_owned_solidworks.py 提供无 CAD 写入的 Windows 会话烟测。默认严格写门槛不变，不加入 P0_RETEST_ATTACH 绕过。
- 修复文档计数与实际枚举不一致时错误返回空清单的问题，支持 pywin32 无参数属性/方法两种绑定。
- p248 新增结构化 bend_attempts（级别/请求加深/失败索引/实际完成数），native 发布失败 JSON 保留 generation 以便联调，仍不把加深请求当成实际几何验证。
- 新增 8 项模拟会话测试；`python work/run_cloud_tests.py`：351 ran / 347 passed / 4 skipped / 0 failures / 0 errors，跨进程锁通过。36 pending_features 未计通过。Linux 没有启动真实 SW。
- 下一步：Gork 使用无 shim 的 --sw-exe 探针核对 PID/句柄/清单，再复测 p248。Windows 启动注册行为、独占证明与释放槽实机结果仍 pending。操作说明见 docs/p0-sheet-metal.md。



## P0-CODEX-004：p248 固定板面漂移

- 基线 e6a6c743fc5c9be3813a31e67923941c60d3379a；保留 Gork partial_deepened_then_flat 原始证据。
- 只读原 DXF 与日志确认：短标记端点距离排名导致 108/109 在 106/107 折起后选中已移动翼板；每组/逐条还重新选择固定区域。中间孔也未被默认选择器排除。
- 修复按完整折弯轴选择同一区域、排除孔、整轮分组/逐条固定同一锚点。未增大释放槽、未改变 t/R/角度或放松会话所有权。
- 新增 5 项 synthetic 回归；修复前有明确短标记候选落在翼板的失败，修复后针对性 19 项通过。本机 `python -X utf8 work/run_cloud_tests.py`：356 ran / 351 passed / 5 skipped / 0 failures/errors；跨进程锁通过。Windows 多出的跳过是 Linux 平台拒绝测试。
- 原始实机 108/109 尚未复测通过；这是已验证代码缺陷的修复，不是宣称全部机械根因或 p248 实机已解决。Gork 现有任务 xi3wwg 负责同一工作副本的后续闭环，完整步骤见 docs/p0-sheet-metal.md。


## P0-CODEX-005：分组折弯诊断

- 基线 4b0a986；为 p248 下一次独占会话复测增加 bend_group_attempts，包含顺序、零基编号、固定点毫米坐标、级别、耗时、创建结果和错误类型。
- 全部/分组/单条尝试均保留；拒绝、断连及后续重建失败可携带已产生的诊断；释放槽重试结果按轮保留。created 只指特征创建，不能替代保存重开和机械验收。
- 新增两项模拟回归，Windows UTF-8 全量：358 ran / 353 passed / 0 failures/errors / 5 skipped；跨进程锁通过，36 pending 合约仍未计通过。未运行新的 SW 实机测试。


## P0-CODEX-006：原生固定面几何核验

- 基线 1e23ab0c07401c4b5ee1d9726655f2c5e525e07f，保留 Gork 固定点生效但 108/109 失败的原始实机证据。
- 确认残余代码缺陷：仅锁 XY 点仍按面积取前两个面；折起翼板可抢占候选并使草图投影到错误平面。synthetic 第三位中央面案例在旧面积逻辑下明确失败。是否是 p248 的全部残余机械根因仍未证明。
- 新增固定面核验：候选须是原始 XY 固定板位置的平面，IFace2.GetClosestPointOn 必须匹配锚点；筛掉倾斜/折起/孔洞/未知面。先筛选再取两张板皮，不扩大槽、不改变折弯方向/位置、不放松所有权。
- 新增 4 项 synthetic 检查；Windows UTF-8 全量 362 ran / 357 passed / 0 failures/errors / 5 skipped，跨进程锁通过。36 pending 合约仍未计通过，未执行新的 SW 实机测试。
- 实机后续：记录 Fixed panel face verification 的候选数，核对两组面确为固定板；若仍失败返回原生特征错误、草图平面及槽交会几何。旧日志中的退出 COM 断连单列为未解决，未擅自归因 CoUninitialize。
