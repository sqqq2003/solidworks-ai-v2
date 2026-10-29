# 计划书对照核查（2026-10-25）

依据：AI_MASTER_PLAN.md、Issue #6/#9/#11/#13/#15/#19/#24、用户八模块及设计意图/影响分析/工程验收要求，结合 #46 统一交测单。范围为源码与入口核查，未进行 Windows 验收或全面回归。

开发基线 dev/cloud-ai = aca899b2d7daf2d0b9a2edabda48a56a477b1711。
PR20 = 092eb0bbeffc03b46502945095c76a64d7c22545；PR28 = e865b3dbbccbeef414f6ce41ba54bfea22923445；PR45核查前 = 37cff9de571de63c728c2ec003b3b21f0a1609d7；PR47 = 9229517de6511218fca6ada050872d6f4cef72ea；PR48 = 1ab7e8e9539f971cf8c59067300fdf6f60ef8643。核查时这些PR均未合并。

| 计划要求 | 实际源码/入口 | 核查结论与剩余工作 |
|---|---|---|
| QL 参数化 | 基线 ql5050px/parameters.py、workflow.py | 有实现；真实OEM映射未补齐，1800×900×1500仅为目标 |
| 受控SW执行 | 基线 sw_session.py、sw_owned_launch.py | 有归属/写闸；#39断连未实机收口，PR47是候选 |
| 装配/传动 | 基线 assembly_builder.py、drive_variant.py、native_machine.py | 有计划及原生适配；真实装配配合/引用/运动/干涉待验 |
| 钣金生成展开 | 基线 solidworks_generator.py、sheet_metal_pipeline.py | 有生成链；保存不代表重开/展开/退出通过 |
| 工程图/BOM | 基线 manufacturing_drawings.py、native_drawings.py、drawing_bom.py | 有任务/原生适配；完整制造关联待验 |
| 整机识别 | 基线 intelligent_scan.py、intelligence.py | 有快照与扫描接口；分类是候选，非已确认机械语义 |
| 参数映射 | 基线 automatic_mapping.py；PR45 mapping.py | 有候选与审核；真实物理绑定仍需确认 |
| 决策与计算 | 基线 intelligent_decision.py、mechanical_selection.py | 有依赖/初选；公式适用条件及真实负载需工程复核 |
| 统一集成 | 基线 integrated.py | 有只读扫描至制造计划链；不得称为整机原生完成 |
| CAD识别/特征IR | PR20、PR47 cad_features.py、cad_topology.py | 独立分支有代码，基线缺这些文件；不支持任意图纸自动唯一重建 |
| 可编辑原生特征 | PR20、PR47 editable_features.py、feature_operations.py | 基础特征及显式映射有实现；规划kind集合与执行支持并非等价，孔/钣金等需专用配方与适配，仍需逐项验 |
| 批处理与恢复 | PR20、PR47 modeling_supervisor.py、recipe_worker.py | 有分进程和checkpoint；真实退出安全待复验 |
| 滚筒总长800 | PR28滚筒改型API/CLI（见该PR交接） | 未合并，不能把筒体800当总长800；真实模型待验 |
| 设计意图/影响 | PR45 design_review、design_platform/native.py | 有保护/依赖/审批门；不是完整机械意图理解，实际host接入待验 |
| 标准件/计算/模板 | PR45 catalogue.py、calculations.py、templates.py | 有可调用初选/模板；依赖真实来源、安装接口和每单钣金参数 |
| 版本回滚/知识库 | PR45 projects.py、knowledge.py | 有快照、新目录恢复和SQLite案例；不自动套用历史修复 |
| 智能交互工作台 | PR45 assistant.py、desktop.py、work/design_platform.py | 有受限滚筒指令/映射界面；任意自然语言设计尚未完成 |
| 工程验收 | PR45 design_review；PR48 test_handoff_audit.py | 有四态和证据核对；不能替代工程师/真实SW验收 |

## 本次补齐的实际功能

此前 manufacturing.consistency 仅检查登记行的材料/修订和钣金字段是否存在，没有与实际生成BOM联查，空清单也可显示一致。现在：

- export_manufacturing 将实际 build_bom 输出传入核查，按零件号+配置联查登记项、材料和聚合数量；缺失、歧义和布尔数量进入复核。
- drawing 行必须绑定同零件号/配置下唯一的 part/sheet/assembly，model_source 指向改型副本，model_revision 等于本次版本。这里只核查声明字符串，不读取SLDDRW真实引用；native_references_verified 始终 false。
- 钣金厚度>0、内R≥0、0<|角度|<180、0≤K≤1且数值有限，direction=normal/reverse；无默认填补。这是基本域校验，不是工厂工艺批准。
- 空登记和空发布版本需复核；生成器输入一次物化，避免导出和检查读取不同数据。

API保持原调用兼容：consistency(register, revision, *, bom=None)。不传bom时 bom_cross_checked=false；现有导出链默认传真实BOM。新增缺参项会使旧示例合理降级为review_required。

10项针对性离线检查全部通过（tests/test_manufacturing_release_audit.py），没有全面回归或Windows实机测试。

## 后续收口顺序

1. 用PR47固定版本验收#39生命周期，保留#22/#39历史结果；不以云端检查替代实机。
2. 分别验收PR28真实滚筒、PR20制造链、PR45平台；这几批当前不能从dev直接调用全部功能。
3. 再建立独立集成候选，核对重叠的project/app/会话文件，做必要离线端到端；不盲目合并正在测试的版本。
4. 本批BOM联查在PR45上增量修改，旧pin证据仍归旧pin，新提交需独立记录；不得追认旧测试已覆盖新代码。
