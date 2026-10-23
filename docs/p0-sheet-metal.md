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
