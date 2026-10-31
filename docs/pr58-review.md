# PR #58 审查与单参数试跑准备

审查范围：已审批映射转换、重复审批/保护件/冲突目标、原生 apply_drive 写入和保存重开读回、首个真实单尺寸案例的验收材料。

发现并修复：
- apply_drive 写入前没有对比模型当前值与审批快照。现在每个尺寸写入前核对有限 SI 读回与带单位基准值；不一致拒绝，须重新扫描审批。
- 原生写后/重开读回使用 abs 差值比较，NaN 可能绕过条件。现在前/后读回共用有限数值及单位验证。

已增加 prepare/audit 工具和 docs/single-parameter-rehearsal.md。工具只核对单尺寸输入与提交证据，不运行 COM、不签发生产放行、不推断源文件引用清单是否完整。

本地离线验证：
- test_variant_acceptance.py：10 项通过（其中原生驱动写前拒绝使用假模型验证）。
- test_decision_bridge.py：10 项通过。
- test_ql*.py：10 项通过。
- work/check_issue13.py：4 项通过。
- compileall 与 git diff --check 通过。
- prepare 合成示例返回 3/blocked；audit 空证据模板返回 3/review_required，10 项 not_run，未误报通过。

未测：真实 Windows API 绑定、独占会话生命周期、实际模型隔离/重建/保存重开、配合/干涉/行程、工程图/BOM 和机械正确性；本轮未执行全面回归。

交测前仍需要：一套真实 QL-5050PX、完整引用清单、实际配置/尺寸、用户指定的新长度及审批、真实模板与工程依据。Gork 先完成旧项目，再按步骤统一试跑。代码可以用于准备试跑，当前不能认定项目已投产。
