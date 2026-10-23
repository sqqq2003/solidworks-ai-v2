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
