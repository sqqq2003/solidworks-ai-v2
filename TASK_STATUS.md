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


## P0-CODEX-007：修正 577109b 的 0 候选回归

- 本机 WorkBuddy 证据目录 wb_p248_577109b_20261023_180236：0/4，Fixed panel candidates=0；明确承认上一版回归，保留原日志。
- 修正不当 GetBox 精度假设，改用类型化 ISurface.PlaneParams；无参数 COM 成员兼容属性/方法。筛面与原生草图/插入点共用精确平面 z；仍排除孔和倾斜/移动面。新增 rejected 原因计数供真实运行定位。
- 三项新增测试：近似 bbox、属性式 COM、真实倾斜法向。前两项在旧 577109b 函数中均明确失败；新实现通过。Windows UTF-8 全回归 365 ran / 360 passed / 0 failures/errors / 5 skipped，跨进程锁通过；36 pending 合约仍不算通过。
- 未在本轮直接执行 SolidWorks；新实机证据待现有 Gork/WorkBuddy 执行者补交。0 候选的真实逐项原因和 108/109 是否成功仍待验证，不将本轮模拟当作放行。先仅 step0，仍0候选时停止加深并回传具体 rejected。


## P0-CODEX-008：草图坐标矩阵方向

- 基线 67fc46b；最新本机 step0 candidates=2 已恢复，仍2/4、108/109拒绝。零候选回归已解除，未宣称 p248通过。
- 确认 _transform_to_sketch 使用连续行作输出点积，与 SW 行向量旋转布局相反，且遗漏缩放。修正为旋转列点积、缩放后平移；身份/镜像矩阵掩盖的问题由旋转坐标回归检出。
- 新增5项测试（含无效输入子测试），旧实现明确失败，新实现通过。共享助手用于折弯、手折参考及孔草图，整轮离线回归370 ran / 365 passed / 0 failures/errors / 5 skipped，跨进程锁通过，36 pending不计通过。
- 本轮增加 Bend sketch coordinates 原生矩阵及模型/草图端点日志，留在本机诊断。下一次先在正式独占会话核对原生 MathPoint.MultiplyTransform 与输出一致，再测step0；未证明本缺陷是108/109全部根因。客户坐标不得公开提交。

## PROJECT-001：整体项目工作台与测试交付

- 基线 e81438b，先同步上游固定面/草图矩阵修复与最新实机证据，不覆盖其他执行者成果。本轮按用户“整体项目”推进，未继续仅围绕p248补丁。
- 新增根app.py：统一钣金、滚筒、车件、整机参数入口，串行队列、识别/计划/原生生成、参数确认、当前任务后停止、项目状态与环境页。后台线程不触碰Tk控件，不强杀CAD进程。桌面显示/点击仍需Windows测试。
- 原CLI增加turned、plan-only与verify-reopen；复用现有车件轮廓/特征算法。修复车件绕过已证明实例而重新GetActiveObject的问题，统一正式会话连接，严格检查保存码与非空文件，保存后按新标题关闭自己文档。
- 三类零件可选关闭重开、重建、实体尺寸核对；滚筒与车件还比对生成结果/计划尺寸。缺失滚筒尺寸默认pending，显式允许的通用默认值仍标来源，不当作OEM实测；化妆螺纹仍不冒充真实螺纹验收。
- 新增project.py：整体能力状态、doctor和JSON清单批量入口；原生失败停止后续任务，离线失败可继续。JSON/任务CSV/参数CSV报告，未知OEM值保持空；退出码0本身不构成成功证据。
- 新增源码测试包构建和SHA清单校验，排除客户CAD、凭据、Git历史和Windows证据，附独立测试记录；不覆盖D盘生产程序。
- 新增15项整体合同测试；全回归 `python work/run_cloud_tests.py`：385 ran / 381 passed / 4 skipped / 0 failures/errors，跨进程锁通过；36原始pending合约仍不计通过。
- `python examples/project_smoke.py`：5项synthetic离线任务，1 analyzed / 2 planned / 2 review_required / 0 failed；未执行SW。完整交接见docs/project-testing.md。
- 装配/配合/干涉/运动、原生工程图仍有骨架/未实现部分；本轮没有伪造这些CAD功能，也没有完成新的Windows整体验收。

源码交接包已独立解压验证：完整回归 385 项，381 通过、4 跳过；离线整项目烟测 5 项均得到预期状态。方程测试使用明确标记的合成夹具，不再要求分发 Windows 原始证据。

## 2026-10-24 QL 统一入口集成交付

- 执行 Issue #6 最新总指令，复用两批 QL 模块和工作台审核修订，在独立分支集成；保留旧钣金/滚筒/车削入口。
- work/project.py ql / batch 与 app.py 已对接 QL 配置、计划、装配预检、BOM、工程图和离线流水线；目标与真实物理映射分别记录，pending 状态向统一报告传播。
- 新增统一配置/任务清单、测试矩阵、源码清单、prepare_ql_handoff.py。详见 docs/ql5050px-unified-handoff.md。
- 本批只做 AST/JSON 语法解析；未执行单测、示例、全面回归、原生 API 或实机验收，不继承旧通过统计。新增回归代码未运行。
- Gork 继续旧 p248，之后统一接测；真实 QL 模型/OEM 映射/Windows driver 仍待提供。集成 SHA 在 Issue #6 评论记录。




## CODEX-PROJECT-RUN-20261024

- 同步基线d392b74，启动统一桌面工作台（窗口响应已核对）；三类零件smoke及QL integrated示例实际运行并生成离线交接包，未知OEM值保持pending。
- 补齐本地开发venv pywin32/comtypes；普通桌面/离线与SW实机验收分开。
- 修复恢复锁Windows os.kill(pid,0)会终止进程的错误，改为只读句柄查询，新增禁止发信号回归。
- 合并原生数学核验硬门槛、逐次Insert结构化诊断、失败证据保留、--no-relief-retries及只读证据检查。无新原生通过声明。
- 完整离线436 ran / 431 passed / 0 failures/errors / 5 skipped；锁通过。另C# Python合约17/17；未编译C#、未运行真实桥。36 pending合约不算通过。说明及一次联合回传矩阵见docs/project-start-20261024.md。


## CODEX-FOLLOWUP-20261024

- 继续跑完离线集成/产物哈希/覆盖保护/冲突拒绝及制造队列首次、resume；5项完成、0失败、1原生pending。
- 修复QL续跑日志value与result.json不绑定、空产物完成项复用、kind不符复用，以及$ref共享对象被下游修改。新增5项回归，旧实现4项明确失败，新实现通过；正常缓存不重跑。
- 完整441 ran / 436 passed / 0 failures/errors / 5 skipped，跨进程锁通过；C# Python合约17项沿用前轮未改模块结果。
- .NET host有但SDK缺失，实际build失败；SW oracle交接原稿在本机指定路径不可读，已向现有执行者请求共享。按ur56w8下一原生阶段仅oracle，不整跑step0。a9rpk4双轨选型仍未验收。详见docs/project-problems-20261024.md。


## CODEX-S2-KEEPALIVE：gh268s双轨回传审查

- WB/Qoder S1保存成功、S2断连发布失败，整体不放行。旧Windows探针/路径断言已由def70f3修复，不重复实现。
- 原生保活缺陷定位：_set_sw_automation_mode把UserControl设False；后台会话关最后文档会退出。现按keep_application_open设置True并严格读回；受控CloseDoc前再次核验，失败不关文档。最终空文档ExitApp保留。
- oracle回传显示typed数学有效但raw dispatch/tuple编组不可靠，补显式SAFEARRAY(double)；不合入温复用绕过。
- p248温测报告改了源图/profile299且非独占、exit139，仅保留几何正面信号，不按原任务或稳定发布通过。Qoder不一致汇总不累计。
- 新增会话/编组/fixture回归，完整478 ran / 473 passed / 0 failures/errors / 5 skipped，锁通过；另C#Python合同17/17。合成fixture dry-run实际simulated_pass，未启动新SW实测。
- 新work/prepare_s2_retest.py输出样本与加载模块哈希、自动轮廓及精确argv；run_sheet_metal新增不可覆盖UTF8诊断日志。docs/s2-retest-20261024.md给出串行WB/Qoder精确跑法，待实机。


## 2026-10-24 Issue #19 / #25 云端批次合并记账（#23 / #26 / #31 / #29 / #30 已合并，#32 待合并）

- 记账口径：本节只补 2026-10-24 当天 Muse 云端批次（#23、#26、#27→#31、#29）与 #23 评审修正（#30）的合并事实；此前各节原样保留，不改写他人条目与历史结论。
- #23 已合并（merge commit `9d65352a`，分支 `feat/issue19-ckpt-teardown` → `dev/cloud-ai`）：S0–S5 阶段 checkpoint、断点续跑、RunLock 死锁自愈、孤儿 staging 归档、崩溃现场包、收尾 5 步日志、COM 逆序释放、最小复现模式；`reopen_inspect` finally 改为逆序释放后才 CoUninitialize。云端自查：14 项新测试 + 113 项相关旧测试通过、4 项原有跳过。Windows 实机验收仍 pending：最小收尾复现 ×3 退出码 0、p248 全流程四项含退出码 0、#20 oracle max_dev ≤ 1e-10、死锁续跑、accept JSON 由 runner 正常写出。
- #26 已合并（merge commit `7363fe49`，分支 `feat/issue25-csharp-bridge` → `dev/cloud-ai`）：`csharp-bridge/` 9 个文件——契约（命名管道 + JSON 行协议 `sw-bridge/1`）、独立审查结论（REVIEW.md）、钣金规则核对（SHEET_METAL_RULES.md）、集成建议与风险及 Gork 矩阵 A1–A8（INTEGRATION.md）、C# 桥接骨架（mock 模式；RealSwApp 在 `SOLIDWORKS_INTEROP` 后）、Python mock 客户端、17 项 mock 测试。云端自查 17 项全过。未测：C# 未在云端编译（无 .NET SDK）、命名管道实测、RealSwApp、SW2022/SW2025 行为，全部 pending_windows_validation。
- #27 → #31 已合并（替代 PR #31，merge commit `f8b20580`，分支 `feat/issue25-runplan-wiring-merge` → `dev/cloud-ai`；原 #27 留言 superseded 后关闭未合并，评论 `6383390043`）：原因——#27（堆叠在 #23 分支上）与已合并的 #26 在 `csharp-bridge/INTEGRATION.md` 上 add/add 冲突；处理——#27 的 4 个改动原样重建在最新 dev 上（`src/bridge_wiring.py`、`tests/test_bridge_wiring.py`、`src/sheet_metal_pipeline.py` 的 bridge= 接线、合并版 INTEGRATION.md），合并版 = #26 完整集成文档 + #27 接线记录单节 appended，两节均未改动、互不覆盖。接线语义：`run_plan` 新增可选 `bridge=` 参数，不传时行为与接线前一致；S1 会话证明、S2 会话 + list_titles 验活、S5 桥接 5 步 teardown 报告；桥接不可用当阶段回落 grade mock + fallback_reason，不中断流程；非零退出码原样记录；锁与 staging 所有权仍归 run_plan。云端自查：8 项新测试全过，回归合计 36 项全过（#23 的 14 项 + pipeline 14 项 + 新 8 项）。边界：桥接契约当时无 build/reopen 方法，生成与重开检查本身仍走 port（见 #32）。
- #29 已合并（merge commit `a7e171cb`，无冲突，分支 `feat/issue25-no-default-k` → `dev/cloud-ai`）：去掉钣金路径默认值——`BendAllowanceSpec.k_factor=0.44` 默认删除改为必填（不传即 TypeError）、`MATERIAL_K_FACTORS` 通用材料 K 表整表删除（审计确认仓库内无调用方）、`audit_variants` 的 `thickness_mm=2.5 / radius_mm=1 / angle_degrees=90` 默认删除改为必填关键字参数、`app.py` 工作台 t/R/角度/K 预填值（2.5/1/90/0.4）改为空；缺输入走 pending_confirmation 或参数检查弹窗，绝无默认数顶替。云端自查：5 项新测试全过，回归合计 35 项全过。Windows 项 pending：CustomBendAllowance 写入与读回、SW2022/SW2025 表现、工作台空字段弹窗流程、生成器全文逐行审计。
- #30 已合并（merge commit `d392b74d`，无冲突，分支 `fix/pr23-recovery-review-guards` → `dev/cloud-ai`；#23 的评审修正）：三项——活/无法探测的锁所有者一律拒绝接管（仅确认死亡才能恢复；旧“活 PID 过期可接管”测试已改正）、收尾退出值原样记录并判失败/待定（139/None 与 release ok=false 不再记为 OK；关闭失败或非空/不可用文档清单时跳过 ExitApp）、检查点产物读取增加双平台路径与 resolve 边界校验（拒绝外部/遍历/逃逸符号链接）。PR 描述自查 21 项通过（7 项新增 + 14 项原 PR23 离线检查）；合并执行时云端核查 43 项通过。Windows 原生验证仍 pending；不声称解决 COM 崩溃。
- 合并后 `dev/cloud-ai` HEAD：`d392b74d`（#30 的合并提交）。合并方式均为 merge commit，不 squash、不强推；main 未动；已合并分支保留未删。另注：Draft PR 按 GitHub API 要求在合并前转为正式（draft:false），为合并必要子步骤，非内容改动。
- #32 未合并（Draft，分支 `feat/bridge-build-reopen`，HEAD `e08b8509`，基线 dev `d392b74d`）：桥接 build/reopen 方法接进 run_plan S1/S2——CONTRACT.md §12（build/reopen 方法、单位显式、错误映射、退出隔离、幂等键）、SwBridge BuildDocument/ReopenDocument（mock 实现；RealSwApp 仍为 stub，pending_windows_validation）、Python 客户端 build()/reopen()（缺参数即 MissingParameterError → pending_confirmation，绝无默认值）、bridge_wiring build_evidence()/reopen_evidence()（executed_via 仅方法成功时为 bridge，否则为 port + fallback_reason）、run_plan 加法接线（S1 先试桥接 build、S2 先试桥接 reopen，任一失败回落 port；桥接报成功却无产物文件为硬失败；S0/S3/S4/S5 不动；#30 守卫不动）、INTEGRATION.md 接线记录与 Gork 矩阵增补 B6–B10、15 项新 mock 测试。云端自查：15 项新测试全过；tests/ 回归 72/72（基线 57：bridge_wiring 8、pipeline 14、no_default_k 5、bend_allowance 6、p0_gork 10、issue19 14）；csharp-bridge 契约测试 17/17。诚实边界：build 目前仅以 plan_id 引用已验证计划，完整几何 IR 传输仍是未起草的设计项；RealSwApp build/reopen 仍为 stub；C# 未编译、命名管道未实测、SW2022/SW2025 行为全部 pending。合并另需用户批准。
- 其他仍 open 的 PR（本节记账时实查，2026-10-24）：#28（Codex #24 单滚筒 800mm，基线旧，合前需 rebase）、#20（统一原生建模，基线旧，合前需 rebase）、#16（#15 CAD 特征首批，未完成）、#17（SAFEARRAY 桥接；与 #20 的桥接取代关系未定性）、#21/#22/#18（证据/文档类，不动代码）、#1（dev→main 记录 PR，head 已为最新 dev `d392b74d`）。Issue #25 仍 open：云端交付（#26/#31/#29/#32）已做，Windows 验收仍 pending，关闭与否待定。
- 跨批共识（写入账本，防后人踩坑）：
  - t、R、K、角度一律按每单输入参数处理，绝无默认值；t=2.5 / R=1 / K=0.36 / BA=3.0 / BD=4.0 只是本厂一次实测用例（2026-10-22 对称 U 槽），不是默认值；#29 已删除 k_factor=0.44 默认与通用材料 K 表；缺输入标 pending_confirmation，永不以默认数顶替。
  - 合并 ≠ 实机验证：上述所有 Windows / SolidWorks 验收项均为 pending_windows_validation；mock 与离线通过不得写成实机通过；accept 结论以 runner 正常写出的 accept JSON 与实机证据为准，事后重建的 accept 须注明证据等级。

## 补记（2026-10-24 合并批：#32/#34/#35/#36/#37/#38 已合并，#33 最后合并）

- 合并前 dev HEAD：`243e269f`。合并顺序与 merge SHA（均为 merge commit 方式，分支保留未删）：
  - #32 桥接 build/reopen（分支 `feat/bridge-build-reopen`）→ `d4183dec`
  - #34 口径统一（分支 `docs/k-value-wording-20261024`）→ `38e88ac7`
  - #35 模块③ DXF 提取（分支 `feat/issue25-dxf-extract`）→ `a1f697c0`
  - #36 模块④ 特征树执行（分支 `feat/issue25-feature-tree-exec`）→ `a7f71a45`
  - #37 模块⑤ 依赖引擎（分支 `feat/issue25-dependency-engine`）→ `d9d9f719`
  - #38 模块⑥ 离线验证包（分支 `feat/issue25-offline-verify`）→ `4fe6e05c`
  - #33（本节所在分支 `docs/task-status-20261024`）在内容批合完后追加本节，再最后合并；其 merge SHA 以 GitHub 合并记录为准。
- 合并过程：6 批均无冲突直接合并。#35/#36/#37/#38 为纯新增目录；#32 改 csharp-bridge/ 与 src/bridge_wiring.py 等已有文件，合并时无冲突；#34 只改 docs/ 措辞。#32/#34/#35/#36 基于旧 dev `d392b74d`，#37/#38 基于 dev `243e269f`，均未 rebase 即合（diff 可干净应用）。
- 合并 ≠ 实机验证：上述各批的 Windows / SolidWorks 验收项仍为 pending_windows_validation；统一验收总表见 `offline_verify/examples/WINDOWS_ACCEPTANCE_PACK.md`（42 项）。
- 遗留项（本批未改，如实记账）：
  - #38 基线漂移：recovery-guards 在 dev 上实测 8 项、基线期望 7 项，已标 diff 未改基线，待归属方确认后随其 PR 更新。
  - 生成器头部 `DEFAULT_BEND_K_FACTOR = 0.44` 残留由独立清理批处理（分支 `feat/generator-no-default-k`），不在本批范围。
  - Issue #25 仍 open，关闭与否待用户/Gork 定。
  - 仍 open 的其他 PR：#28（Codex #24 滚筒）、#20（统一原生建模）、#16、#17、#21/#22/#18（证据类）、#1（dev→main 记录 PR）。


## 补记 2（2026-10-25 替代记账：原 #33 未合并，#40 已合并）

- 本替代分支基线：dev `7696e18d`（#40 的合并提交）。
- 原 #33（分支 `docs/task-status-20261024`，head `70bce193`，含追加提交 `54e5bfb5` 与并集拼合提交 `70bce193`）**未合并**：dev 的 `TASK_STATUS.md` 在前进过程中多了 Codex 的 `CODEX-PROJECT-RUN-20261024` / `CODEX-FOLLOWUP-20261024` 两节，与 #33 在文件尾部同一锚点的追加构成 add/add 型结构性冲突；本地 git 复现证实，只要合并基准还是旧 `d392b74d`，API 合并即判冲突，与内容取舍无关。故不硬合、不 force-push、不 rebase 原分支。处理沿用 #27→#31 的先例：从最新 dev 新开本替代分支，把上两节记账原文接在 dev 版 `TASK_STATUS.md` 之后（旧节一字未改），本替代 PR 合并后在原 #33 下留言说明并关闭原 #33（未合并关闭）。
- 订正：上节“补记”中“#33 最后合并”一语已过时——原 #33 实际未合并，记账承接关系以本节为准；上两节中的 PR 号、分支、merge SHA、测试数等事实原样保留。
- #40 已合并（merge commit `7696e18d`，分支 `feat/generator-no-default-k` → `dev/cloud-ai`）：删除生成器头部 2 行死定义（`DEFAULT_BEND_K_FACTOR = 0.44` 注释 + 定义，6085 行 → 6083 行）+ 新增 `tests/test_no_generator_default_k.py`（5 项测试）；审计确认全仓库 174 个文件无任何引用点，故无回落默认值转换、无行为变化；5 项测试全过，其中 3 项在清理前原文上失败，证明可抓住残留。至此“t、K 绝无默认值”规则在代码侧彻底落实（文档侧见 #34）。
- 本节所在替代 PR 的 merge SHA 以 GitHub 合并记录为准；合并方式为 merge commit，分支保留未删，main 未动。
- 仍 pending（本批未改，如实记账）：
  - Issue #39：7c787deb（`Keep owned SolidWorks alive across S1 close and S2 reopen`）已在代码侧修复 S1→S2 保活根因（UserControl=True + 严格读回、CloseDoc 前再核验、显式 SAFEARRAY(double)），并附 `docs/s2-retest-20261024.md` 精确串行重测跑法；但新补丁实机通过仍待 WB/Qoder 串行重测（同一受控 PID 跨 S1 关最后文档 → S2 重开 → 重建读回 → 展开导出，`keepalive_verified=true`）；`_pid_alive` 的 Windows 分支已用 `_windows_pid_alive`（属 def70f3 一批）；WB-TEST-001 的同名测试在 dev 树内无对应项，修复认领以 def70f3 为据，待重测确认；#39 本身仍 open，不急于关闭。
  - #38 基线漂移：recovery-guards 在 dev 上实测 8 项、基线期望 7 项；来源已查清——def70f3（`def70f318`）新增 `test_windows_probe_never_sends_a_signal` 一项；修正以 Draft PR 另行送审，不手改数字凑通过。
  - Issue #25 仍 open，关闭与否待用户/Gork 定；Gork 42 项统一验收总表（`offline_verify/examples/WINDOWS_ACCEPTANCE_PACK.md`）仍待 Windows 实机执行；合并 ≠ 实机验证。


## P0-NATIVE-COM-20261025：SAFEARRAY、板/支架类型、轴保存后断连

- 基线 `aca899b`（`dev/cloud-ai`）。本轮只做 Windows r2（证据 pin `36729775`，干净主机）对应的 P0。云端只跑离线/模拟。`native_acceptance` 仍是 `pending_windows_validation`。没有 SolidWorks 实机通过。
- 板/支架：文档创建后约 75ms 失败，`com_error -2147352571`（DISP_E_TYPEMISMATCH），`argErr=8`。这与 `SelectByID2` 的 Callout 传了裸 `None` 的已知签名一致，发生在切除之前。Callout 改为 `VARIANT(VT_DISPATCH, None)`，坐标为 `0.0`。固体切除/拉伸的深度、拔模角、起始偏移改为 double；`NormalCut` 在固体路径显式为 False，钣金通孔仍为 True，不把钣金孔参数抄到固体。空零件第一刀拉伸先试 `Merge=False`。
- 轴：保存已写出 `part.SLDPRT`，下一次 COM 是 `CO_E_OBJNOTCONNECTED`（-2147220995，中文「对象没有连接到服务器」）。该 HRESULT 原先不在断连表里，收尾会把它当成普通失败并可能继续 ExitApp；保存后的 `IModelDoc2` 也继续被用。现已列入断连，保存后先重新取 `ActiveDoc`，再只 `CloseDoc` 当前文档。断连记为 `post_save_com_disconnected`，不标通过，不 ExitApp，不杀进程。任务 STA 已初始化时，生成函数不再套一层 `CoUninitialize`。
- 数学数组：沿用 PR #17 的 `src/sw_math_arrays.py`（`double_array` / `CreatePoint` / `CreateTransform`），草图点与装配 `CreateTransform` 走这一处。不另写一套编组。
- 独占启动：仍要 `--sw-exe`、PID/句柄、空文档清单后才 claim。拒绝第二实例和 PID 不符的会话。没有 `P0_RETEST_ATTACH`，没有温复用验收路径。
- 未做（P1，本 PR 不做）：Codex 风格 UI（PR #54）不合并；装配配合/干涉/运动和原生工程图仍是骨架；36 个 `pending_features` 不计通过；A01 几何跟随 / Pack and Go 不在本 PR；p248 钣金加深和释放槽另 PR，说明仍在 `docs/p0-sheet-metal.md`。
- 建议 Gork 在干净单实例 Windows 上复测：plate、bracket、shaft，以及 owned-launch。看 SelectByID2 / 固体切除是否还报类型不匹配，shaft 保存后是否还能重开；断连必须是失败证据，不是通过。`two_bend` 上次是 `not_run`，等前一件收尾明确后再跑。
- 离线：`python work/run_cloud_tests.py` → 524 ran / 520 passed / 0 failures / 0 errors / 4 skipped（原有 DWG、LibreDWG、基线哈希跳过），跨进程锁通过。36 个 `pending_features` 不计通过。`sw_live=not_applicable_on_linux`。
