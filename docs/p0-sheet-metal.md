# P0：二维 CAD → 原生可编辑钣金（Issue #4 / #5）

这是第一轮可运行云端实现，复用 cad_analyzer、profile_selection、profile_sanitize、bend_allowance、generate_sheet_metal 和 export_flat_pattern_dxf。没有 Windows 实机通过声明。整机 A01 改型转 P3。

## 可运行命令

纯模拟，自动建立明确标注 synthetic 的二维板件（100×80、内孔、一道折弯）并输出 JSON trace：

```bash
python examples/sheet_metal_dry_run.py
```

对 Windows 本地样例先查看识别和计划，再显式确认板厚、R、角度、K、方向和折弯候选：

```bat
py work/run_sheet_metal.py sample.dxf
py work/run_sheet_metal.py sample.dxf --profile 0 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.4 --direction normal --confirm-bends --dry-run
py work/run_sheet_metal.py sample.dxf --profile 0 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.4 --direction normal --confirm-bends --relief-bends 0 --live
```

--profile 和 --relief-bends 为零基索引。第一条命令参数未全时返回 3/pending，查看 plan.hole_indices、bend_indices、source_units。缺参数、方向、折弯分类确认或原图无单位时不能执行；原图无单位且操作者已确认毫米才能加 --confirm-unitless-mm。DWG 沿用现有转换器，缺少转换器会明确失败。不要把单位未知的英寸图确认成毫米。

--live 仅 Windows，可用 pywin32、SolidWorks、类型库及现有 sw_session 独占任务 STA 的机器才允许。不会为了跑通而接管未知进程。若缺少证明归属的会话，拒绝并保留错误，交由 Gork 现有会话桥接处理。

## 契约和验收

sheet_metal_pipeline.build_plan 输出 schema v1：来源 SHA、规范到 mm 的 DrawingAnalysis 指纹、代码指纹、轮廓/孔/折弯索引、操作者输入的参数、K/BA/BD 计算预览、释放槽规则及特征步骤。孔内轮廓选择不会偷偷提升为外轮廓；自交轮廓、嵌套岛屿拒绝自动生成。曲线折弯保留 pending。最初只覆盖同角度/同方向的绘制折弯；混合角度、多板厚、多实体、边线法兰需要后续扩展，不猜测。

WindowsSheetMetalPort 调用原有生成器，auto_bend=True、cad_import=False（使用已绑定指纹的解析几何重画原生草图）、close_saved_document=True。生成后必须重新打开磁盘零件、成功重建，识别 SMBaseFlange/SheetMetal/FlatPattern 原生特征，读取可访问的 SheetMetal 定义、t/R/K，并检查原生折弯特征数量。部分折弯、平板加参考线、STEP/导入实体、无法读回参数都不算通过。不同 SW 版本的 feature type/接口差异需以实际日志修正，不降低验收门槛。

然后用现有 SW 展开 API 导出 DXF，并用 ezdxf 验证可读取、非空。存在 DXF 不是机械验收：展平尺寸与下料正确性仍需 Gork 测量。reopen_inspect 的“editable”意味着存在可访问的原生特征定义，并不宣称所有草图已完全约束。

run_plan 在唯一 staging 目录生成，全部检查通过后才将整个产物目录发布。每次有跨进程发布锁；失败调用 abort，清理仅本次 staging，保留独立 failure-*.json；失去会话或清理失败时标记 recovery_required 并保留 staging。超时写入被 sw_session 封锁，不启动第二个 COM 写者。已存在源图纸、零件、DXF 不覆盖。恢复运行校验 plan/source/geometry/code 和产物 SHA；不同 K 因子产生不同计划和目录。

MockSheetMetalPort 永远只写 *.trace.json，reopened/editable=false，sw_live_verified=false。它的 simulated_pass 只证明合同可运行。

## 用户回归场景

- t=2.5、R=1：释放槽复用规则 width≥2.5，越过中心线深度 4mm；这是算法规则，不是样例图纸测量。只对操作者明确选择的折弯应用，失败诊断不自动伪造槽。
- 折弯中心失败：BendRejected/重建失败进入失败清理，不能用平板参考草图通过。保留 API 错误，交由 Gork 提供最小真实复现。
- K 修改但展开不变：diagnose_k_change 必须区分 fixed_blank（二维毛坯尺寸固定）和 fixed_outside_legs（固定折后外尺寸）。前者展开长度不变可能正确；后者单折弯理论差为 ΔBA=θ·t·ΔK。例如 t=2.5、90°、K 0.3→0.4，对应 0.392699mm。还必须读回本机特征上的 K，不能只看理论或文件名。

## Gork 首轮需返回的证据

源样例摘要与单位、确认后的参数/折弯索引、SW 版本和会话归属、CLI JSON、特征类型与 t/R/K 读回、重开/重建结果、SLDPRT 和 DXF 工作目录、实际展开测量、失败阶段/错误码。客户源图和 CAD 产品留在本机，仓库只提交可共享的诊断/测试。当前仓库没有可用于这次验收的真实钣金源样例，本轮烟测和新增测试均为 synthetic。

## 开发期间收到的实机记录

Gork 在 c6e00d8 / b0c4dec 中提交 p190、p209、p243 的 Windows 记录（results/windows/p0_sheetmetal_accept_*.json）：报告 SMBaseFlange、SheetMetal、SM3dBend、FlatPattern，重建和展开 DXF 成功。这些是 Gork 现有本机工具的实机进展，不是本次新适配器的运行结果。记录尚缺 t/R/K 原生读回、源/参数/代码哈希以及确定的关闭后重开链路；本轮新验收门槛继续保留，不因顶层 status=pass 而补写缺失证据。

## Gork K / p248 反馈修复（2026-10-23）

Issue #4/#5 报告：本机旧 CLI 没有 --k-factor，基体法兰及绘制折弯创建时使用 None；事后修改返回 True，但实际 K 保持 0.31。p248 的部分成功被参考草图吞掉，没有进入加深重试。

本次修复：

- 原 `src/sw_tool_cli.py` 增加 --k-factor；传递 BendAllowanceSpec 到实际创建调用。BaseFlange/BaseFlange2 的 CustomBendAllowance 参数与 InsertSheetMetal3dBend 均使用该对象，不在显式请求失败时悄悄回退 None。
- 对 CreateCustomBendAllowance 的返回接口先转成生成类型库的 ICustomBendAllowance，再写 Type/K/BD/BA。Gork 报告过动态 setter 访问冲突，故没有在云端调用真实 COM，也不承诺类型化之后已消除本机崩溃；需独占工作会话实测。
- 重建后和保存前，从新的 SheetMetal 定义读取补偿类型与 K/BD/BA；读回仍 0.31 或类型不符则抛错，不保存、不发 success。原生适配器重开后再验证 t/R/K。
- 全部同草图→分组→逐条尝试结束仍有未折成项时，抛 BendRejectedError，保留 completed_bend_count。放弃本次未保存文档，再用原图重跑 relief_step=1/2（累计 +1.0/+1.5mm）；不叠加修改上一次模型。三次仍失败，旧 CLI 保留明确 degraded/exit3 的平板参考输出；新原生管线拒绝把它发布成通过。
- 多条折弯可合并成一个 SM3dBend。验收改成“存在原生折弯特征 + 生成器完整完成条数 + 重开重建”，不再错误要求特征数等于折弯线数。该完成条数是生成器记录，仍不是对每个折弯角度的机械测量。

Gork 在仓库克隆的独占工作会话内可使用（旧 CLI --profile **从 1 开始**，不要和新 work/run_sheet_metal.py 的零基索引混用）：

```bat
py src\sw_tool_cli.py --mode sheet --input <工作副本.dwg> --out <新的独立目录>\p209-k025.SLDPRT --profile 209 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.25
py src\sw_tool_cli.py --mode sheet --input <工作副本.dwg> --out <另一个新目录>\p209-k050.SLDPRT --profile 209 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.5
```

检查 done 事件中的 requested_k_factor / k_factor_readback / bend_allowance_verified / relief_step_used。再关闭重开、读取特征值并导出 DXF；区分固定毛坯与固定折后外尺寸，不能仅用 bbox 相同判 K 是否生效。

p248 再测要求记录每轮 attempt、relief_step、实际几何改动及未完成条数。当前真实矩形内孔释放槽样本仍不存在；边缘缺口与孔槽分开记录，不补造实机证据。继续保持 blocked/partial，直到 Windows 重新验证。仓库代码不自动覆盖 D:\工程\钣金导入\程序 的客户程序。

### 同步 Gork 后续证据 b1319a0

p0_sheetmetal_accept_kfactor_fix.json 报告本机补丁已让 K=0.5/0.25 读回匹配，直接 BA=10/1 控制组也读回匹配，但 DXF bbox 均未变化。这说明旧“始终读回 0.31”的阻塞已经在 Gork 本机补丁上解除，尚不能单凭相同 bbox 断定展开引擎忽略补偿。

同一展开毛坯重生成的尺寸基准必须确认。新增工具默认保持 pending_dimension_basis；只有操作者确认固定毛坯时才这样运行：

```bash
python work/audit_k_factor_evidence.py results/windows/p0_sheetmetal_accept_kfactor_fix.json --thickness 2.5 --radius 1 --angle 90 --basis fixed_blank
```

该证据审计在 fixed_blank 假设下得到 consistent_fixed_blank_pending_folded_measurements，K 持久化匹配、平料差=0 与假设一致；若输入 fixed_outside_legs 则仍是 mismatch。两种审计均退出 3，不是实机通过。理论 ΔBA≈0.982mm 不能脱离尺寸基准直接要求 DXF bbox 变化。

Windows 新适配器在关闭重开后，会切换 FlatPattern 状态，分别读取折叠和展平实体的模型坐标 bbox（mm），恢复初始抑制状态，不保存；选择/重建/测量/恢复失败会阻止继续导出验收。结果在 reopen.geometry_states。下一轮对两组 K 比较折叠实体、真实展平实体和 DXF 三者，另行记录具体法兰/折弯尺寸；模型轴与 DXF 轴可能不同，不能未经对齐直接按 bbox 宽度相减。

## 正式独占进程入口与 p248 重试日志

Gork 对 f563120 的复测报告：K 写入/保存/重开正确；同源毛坯的展开尺寸相同，折叠 Z 尺寸已有约 0.98mm 差异。会话部分用过 P0_RETEST_ATTACH shim，这不属于本仓库的正式归属证明；以下入口不使用该 shim，也不放松 require_model_write。

先在独立仓库工作副本上跑一次**无 CAD 写入**的 Windows 会话探针（把路径换成实际安装位置）：

```bat
py work\probe_owned_solidworks.py --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --out runtime\owned-session.json
```

流程为 Popen 启动指定 EXE → 保留进程 lifetime handle → 只读查找 COM 注册对象 → GetProcessID 与新 PID 匹配 → 通过保留句柄验证进程存活/真实 image → 完整文档清单为空 → claim_spawned_process。已有活动 SW 对象只用于只读候选匹配，不自动获得写权限；若新进程转发给旧实例后退出、COM PID 不符、文档计数与枚举不符或有未知文档，拒绝写入，报告本次 PID，不结束未知会话。Windows 会话注册、许可证/启动行为仍需实际验证。

正式建模入口（旧 CLI 的 profile 从 1 开始）：

```bat
py src\sw_tool_cli.py --mode sheet --input <独立工作副本.dwg> --out <新的独立目录>\p248.SLDPRT --profile 248 --thickness 2.5 --radius 1 --angle 90 --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe"
```

K 对照时对 profile 209 分别加 --k-factor 0.25 / 0.5，输出必须是两个新路径。更完整的生成→重开→测量→展开→DXF 管线，可在 work/run_sheet_metal.py --live 上加同样的 --sw-exe，注意该脚本的 --profile 使用**零基索引**（p248 对应 247）。未给 --sw-exe 的路径仍保持原有严格归属门槛，不自动接管正在运行的 SW。

每次写入前重新核对 retained handle、COM PID 和当前文档归属。生成/重开/导出复用同一对象，不再重新 GetActiveObject；中间步骤不 ExitApp。结束时只在归属仍有效且清单为空时请求本次实例 ExitApp；不强杀。session/session_end 和探针结果提供 PID、image、attached_existing=false、cleanup_status（exit_requested 或 left_open_for_recovery），exit_requested 不是已确认进程退出。失败证明会保留新进程以供恢复，不能手动把别的 PID 填成 spawned PID。

p248 的 done 事件新增 bend_attempts，逐轮包含 attempt、relief_step、请求累计 relief_extra_mm、status、failed_bend_indices、completed_bend_count、错误类型；成功轮还报告 relief_slot_count。原槽/+1.0/+1.5mm 的请求记录不能替代实际槽几何变化证据。全部失败仍为 degraded/exit3；原生发布管线拒绝通过，并在 failure JSON 中保留 generation/bend_attempts。当前没有真实矩形内孔释放槽样本，保持未验收，不用模拟补上实机结论。

同步时需要同一提交的 src/sw_owned_launch.py、sw_session.py、solidworks_generator.py、sw_tool_cli.py 及所用管线模块，避免混用旧归属函数。不自动覆盖 D 盘客户程序。正式复测需提供 owned-session.json、session 事件和 p248 每轮日志；在此之前独占会话及释放槽实机验收仍 pending。



## p248 固定板面漂移修复（待 Windows 复测）

只读复现当时的 DXF：原选择器按短折弯标记的有限端点距离排名，四折弯优先落在翼板；106/107 先折后，108/109 的前两候选又落在已折起的翼板。单条重试还会切换到别的板面。这个可重复的代码缺陷与“槽扩大过但仍失败”同时存在，不能据此认定 p248 的机械根因已全部解决。

现在按完整折弯轴划分固定板面区域、排除孔，并将同一锚点传给全部分组与逐条重试；显式锚点不能在孔内或折弯轴上。扩槽幅度和最大重试次数保持原值，没有自动增加切口。Synthetic 回归不包含客户 CAD 几何。

Gork 复测请使用当前提交的完整源码，在独立 C 盘工作副本中运行；不覆盖 D 盘程序，不使用 P0_RETEST_ATTACH。先通过 work/probe_owned_solidworks.py --sw-exe 的独占证明，再使用现有 sw_tool_cli 的 --sw-exe、--profile 248、t=2.5/R=1/90 度，输出到新的空目录。必须记录 `Fixed panel pinned for all bend groups`、每次原生折弯的 pick、bend_attempts、4/4 实际完成数、重建、关闭保存重开和展开验证。

若仍为 2/4，不再把“改动=1”作为释放充分证据：需要失败原生特征错误以及实际槽与失败折弯的对应关系，再区分选择/折弯顺序和槽深不足。flat fallback 仍为 degraded；不得发实机通过。Windows 离线回归建议 `python -X utf8 work/run_cloud_tests.py`，避免系统默认 GBK 误读已有 UTF-8 方程 fixture。


### 分组折弯诊断（P0-CODEX-005）

生成结果新增 `bend_group_attempts`；使用释放槽重试入口时，每轮 `bend_attempts` 内也保留该字段。每条记录包含 `sequence`、`bend_indices`、`index_base=0`、`fixed_point_mm`（源图毫米坐标）、`relief_step`、`elapsed_seconds`、`status` 和失败时的 `error_kind`。界面显示编号时加 1。

`created` 仅表示该次特征创建调用成功，仍须核对重建、保存重开、4/4 完成数和展开。固定点记录是请求的锚点，不是已验证的原生面身份。保持现有 Gork 任务，不重复派发；实机工作副本同步后使用原复测步骤。客户坐标应保留在本机诊断中，公开提交前脱敏。


### 固定面筛选（P0-CODEX-006）

锁定源图 XY 锚点后，仍需证明候选原生面属于固定板。现先筛选原 XY 固定板位置的平面（z=0 或正负板厚），再用 IFace2.GetClosestPointOn 对锚点做裁剪面内核验，最后从有效面中最多尝试两张板皮。面积大的折起翼板不再挤掉中央板面。无法读取几何时拒绝该面；COM 断连上抛，不重连未知实例。

API 依据：[IFace2.GetClosestPointOn](https://help.solidworks.com/2022/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFace2~GetClosestPointOn.html)。1e-7 m 是计算核验容差，不是制造间隙。当前生成器固定板保持原 XY 平面；不支持的移动固定板应阻断，不猜测变换。

复测保持 t/R/角度、槽加深上限及独占启动步骤。收集 Fixed panel face verification 候选数以及 bend_group_attempts。候选为 0 时先检查原生面几何绑定；不要恢复面积回退。仍须 4/4、重建、保存关闭重开和展开均通过才可验收。


### 0 候选回归修正（P0-CODEX-007，取代上一节的包围盒判平面）

577109b 的 Windows 复测回退为 0/4：所有组均 candidates=0。该版用近似 GetBox 差值判定平面是错误的精度假设；[官方文档](https://help.solidworks.com/2021/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFace2~GetBox.html) 明确禁止将其用于精确比较/计算。

现在经类型化 ISurface.PlaneParams 读法向与米制基点，支持无参数 COM 方法/属性两种绑定；选面和草图两处 z 坐标共用真实平面。孔洞仍用裁剪面最近点核验；不回退面积选面。日志包含 rejected 原因计数。两项新回归在旧实现明确失败，新实现通过；倾斜面仍被拒绝。

实机优先只跑 step0；若仍 0 候选，直接回传 rejected 计数及对应面 PlaneParams/最近点返回或异常类型，先定位真实原生拒绝项，不重复三档加深。只有 candidates 恢复且原生 Insert 失败时才继续原有有界流程。当前修复了可复现代码缺陷，尚未证明哪一项造成该次真实 0 候选，也未宣称 108/109 通过。
