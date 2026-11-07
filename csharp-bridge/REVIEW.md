# Issue #25 独立审查结论：钣金基线、展开计算与 COM 生命周期

> 审查范围：Issue #15、#19，PR #16 / #17 / #18 / #20 / #23，以及 `dev/cloud-ai` 分支的相关代码。
> 审查方法：只读。Issue 全文、PR 标题与分支、核心代码原文均已读到；PR #17 / #18 / #20 的**正文描述未读到**（工具未提供该接口），其合并状态以标题与分支为准，见"未确认"一节。
> 证据等级说明：本文所有"已证实"均指代码原文或已落盘的实机文件；"待证实"指需要 Windows 实机证据；模拟/离线通过在任何情况下都不写成实机通过。

## 1. 一句话结论

**折弯本身已证实能过，收尾尚未证实能干净退出；展开公式链已证实自洽，实机读回尚未证实完整。** 把"4/4 折弯成功"说成"钣金引擎稳定"，是目前最大的证据等级错误，本审查首先纠正它。

## 2. p248 基线：已证实 vs 待证实

### 已证实（有落盘文件或代码原文支撑）

- **4/4 折弯插入成功**：PR #18 分支（`cursor/qile3-windows-evidence-20261024-0614`，未合并进 `dev/cloud-ai`）的两份实机 accept JSON 均记载 4 个折弯全部插入、展开验证通过、产物已落盘。
- **产物保存成功**：12:41 复测记载"零件已保存"，随后才崩溃——崩溃点在保存之后。
- **崩溃真实存在且可复现类别一致**：11:18 run 为 EXIT=139（COM teardown，pythoncom uninit / OLEAUT32），12:41 retest 为 EXIT=-1073741819（0xC0000005 ACCESS_VIOLATION），同属"生成后 COM 卸载阶段崩溃"一类。
- **第二次 accept 是事后重建的**：12:41 的 accept 注明 runner 未能正常写出，是依据 step0_warm.log + 磁盘文件重建的——这份 accept 的证据等级低于正常写出的 accept，引用时必须注明。
- **云端生命周期纪律已建立**：`sw_session.py` 只关 owned 文档、ExitApp 前必须 verified_exclusive + 可枚举标题 + 无 foreign 文档、断开连接时不 ExitApp、不按进程名杀进程；`sw_owned_launch.py` 的独占 spawn 要求 PID 绑定证明与零文档库存。这些是好的设计，应保留。

### 待证实（pending_windows_validation，缺一不可）

- **崩溃根因**：CoUninitialize 时序、SafeArray 重复释放、ExitApp 本身、warm-reuse 附着路径特有问题——四者尚未区分。最可疑的是 `dev/cloud-ai` 的 `sheet_metal_windows.reopen_inspect`：其 finally 里先关文档、随后直接 `CoUninitialize()`，而此时 app / model / feature / definition / custom 等 COM 包装对象仍被 Python 变量引用，之后 GC 释放时 COM 库已卸载，是经典的 teardown AV 成因。**这是代码原文确认的嫌疑点，不是实机定论。**
- **独占 spawn 路径的表现**：两次 p248 实机 run 均为 warm-reuse 附着（PID 16564，`verified_exclusive=false`），独占 spawn 路径下 p248 全流程 + 退出码**没有任何证据**。
- **PR #23 的收尾修正是否治愈崩溃**：PR #23（`feat/issue19-ckpt-teardown`，Draft）在分支上修正了释放顺序并补齐 checkpoint/死锁自愈/崩溃现场包，Linux 测试通过；但它**尚未经过 Windows 实机验证**，不能写成"已修复"。

## 3. 展开计算：已证实 vs 待证实

### 已证实（本审查在 Linux 上用仓库原文代码实测）

- 公式链自洽：BA = θ(R + K·t)，OSSB = (R + t)·tan(θ/2)，BD = 2·OSSB − BA；由 BD 反推 K 的公式与正向公式互为逆运算。
- **参数化验证**：t/R/K/角度四组非工厂参数（1.5/1.0/90°/0.44、3.0/2.0/90°/0.40、2.0/1.5/120°/0.33、0.8/0.8/90°/0.50）正向算 BD 再反推 K，全部精确回到输入 K（误差 < 1e-9）。证明公式链与参数传入无关，t、R、K 走参数是成立的。
- **工厂用例互验**（一次实测，非默认值）：t=2.5、R=1、θ=90°、K=0.36 时，BA=2.9845≈3.0、BD=4.0155≈4.0，与车间标称值在取整精度内一致；BD 法下料 124 − 2×4.0155 = 115.97 ≈ 演示值 116.0（不对称 U 槽外形 38+38+48）。另注意：由取整后的 BD=4.0 反推得 K=0.3639，与标称 0.36 相差 0.0039，属取整误差，不构成矛盾——车间标称值本身就是取整后的数。
- **几何基准已区分**：`k_factor_evidence.py` 明确 `PIPELINE_GEOMETRY_BASIS = fixed_blank`（基体法兰来自闭合展开草图 + 绘制折弯）；固定毛坯基准下，改 K 时展开/DXF 外形差为 0 是**预期**，K 的几何效应体现在折弯后外形尺寸上。把"DXF 外框不变"读成"SolidWorks 忽略了 K"是错误的。

### 待证实

- 原生读回完整性：thickness / radius / k_factor 三项在重开后与计划一致（`validate_native` 的要求），目前只有 p248 场景的部分证据，未形成全量读回矩阵。
- 折弯后外形尺寸随 K 的变化量（`k_factor_evidence` 要求的 folded_body_dimensions_for_each_K）尚未提供实机测量。

## 4. PR 状态逐项（标题与分支已核， 正文未读）

| PR | 标题要点 | 状态 | 审查意见 |
|---|---|---|---|
| #16 | Issue #15 CAD 特征规划与诊断首批实现（未完成） | Draft，未合并 | 标题自带"未完成"；#15 的特征树引擎仍在进行中，引用时不许写成已交付 |
| #17 | 修正 Gork 反馈的 SW 数学数组编组并提供独占 Oracle | Draft，未合并 | VT_ARRAY\|VT_R8 桥接 + oracle，**尚未经 Windows 验证**；不许假定等价于 Gork 已通过的工作副本 |
| #18 | Qile3 2026-10-24 p248 与 Issue15 实机证据 | Open（非 draft），未合并进 dev/cloud-ai | 两次 p248 accept JSON 与 HANDOFF、日志、manifest 在该分支内可查；是 #19 审计的证据源，但本身不是代码交付 |
| #20 | Issue19 统一原生建模、审核批处理与 Gork 一次性交测版 | Draft，未合并 | 唯一新增 src 文件是 `sw_math_arrays.py`（类型化 SAFEARRAY 桥接 + oracle，标注 `p248_acceptance: unverified`、`cad_written: False`）；后续工作复用它，不另写一套桥 |
| #21 | PR20 Issue19 Qoder+WB 验收证据（文档） | Open | 证据类 PR；正文未读，内容待 Gork 确认 |
| #22 | PR#20 Windows retest 证据（dual-source fail） | Open | **标题提示 PR #20 的一次 Windows 复测存在 dual-source 失败**；正文未读，该失败的性质与影响待 Gork 确认，在确认前不许写 #20 桥接"已验证" |
| #23 | Issue #19 stage 2：阶段 checkpoint、崩溃恢复、收尾日志（云端部分） | Draft，未合并 | 本审查的协作基线：S0–S5 checkpoint、死锁自愈、孤儿归档、崩溃现场包、5 步收尾日志；Linux 测试通过，Windows 待验 |

## 5. #15（特征树引擎）现状

- 目标五项（几何识别、特征树 IR、建模任务生成、钣金规则校验、错误诊断）已有第一批实现（PR #16），但原生逐特征 COM 构建器仍缺（#19 P1-A），属于进行中。
- 规则上已确立且本审查认同：缺关键视图/板厚/折弯方向/K 因子时 pending_confirmation；制造规则与执行计划分离；诊断默认只给修复计划、不自动改写原件。

## 6. 本审查新发现（不在 #19 审计报告里）

1. **`dev/cloud-ai` 的 `reopen_inspect` 释放顺序嫌疑是代码原文可指认的**：finally 块先关文档、后 `CoUninitialize()`，中间没有任何显式包装释放与 `gc.collect()`。PR #23 在分支上改了这一处，但 dev/cloud-ai 主线仍是旧顺序——在 #23 合并前，任何基于 dev/cloud-ai 的实机 run 都仍带这个嫌疑。
2. **`BendAllowanceSpec` 存在一个通用默认值（k_factor=0.44）**：它是教科书类通用初猜，不是某单的制造依据。本审查的桥接客户端对此采取零容忍：缺 K 一律报错 pending，绝不回落到任何默认值；调用方在构造 `BendAllowanceSpec` 时必须显式传入每单的 K，否则应视为未确认输入。
3. **生成器最小释放槽常量未核对**：`build_plan` 的 relief_rule 引用 `minimal_relief_width_mm` / `minimal_relief_depth_past_centerline_mm`，其来源标注为 `existing_generator_rule_not_measured`（生成器规则、非实测）。生成器文件过大，云端未逐行读到这两个常量的具体实现——本审查**不背书**它们的数值与 SHEET_METAL_RULES.md 的规则是否一致，列为待 Codex/Gork 核对项。
4. **PR #22 的标题是一个风险信号**：若 PR #20 桥接的 Windows 复测确实存在 dual-source 失败，则 #17 与 #20 两套桥接的关系（取代/并存/分工）必须先由 Gork 定性，任何一方不得擅自宣布另一方作废。

## 7. 未确认清单（本审查明确不掌握）

- PR #17 / #18 / #20 / #21 / #22 的正文描述与评审意见。
- 12:41 retest 之后有无更新的实机复测、SW 版本与会话归属细节。
- 生成器最小释放槽常量的具体数值。
- `solidworks_generator.py` 全文（231KB，云端未逐行审计）；本审查只读了接口层与 pipeline/windows/session/launch 模块。
