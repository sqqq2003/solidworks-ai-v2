# QL-5050PX 统一交接

执行 Issue #6 的 2026-10-24 最新总指令。合并五模块及框架修订源码，在现有 work/project.py / app.py 上新增实际 QL 路由；不重做既有零件引擎。本批未运行单测、示例、全面回归或原生验证；仅做 Python AST 和 JSON 语法解析。Gork 先收尾旧 p248，再统一接测。

## 入口

```bash
python work/project.py ql --action plan --config examples/ql5050px_unified_config.json
python work/project.py ql --action assembly --config examples/ql5050px_unified_config.json
python work/project.py ql --action drawing --config examples/ql5050px_unified_config.json --output-dir runtime/ql-drawing-new
python work/project.py ql --action pipeline --config examples/ql5050px_unified_config.json --output-dir runtime/ql-pipeline-new
python work/project.py batch examples/ql5050px_project_jobs.json
python app.py
python work/prepare_ql_handoff.py --out runtime/ql-source-handoff.zip
```

这些命令本批未执行。示例只有模拟夹具参数，不能制造或认作真实 QL。直接 ql 子命令输出完整 workflow JSON；batch/GUI 使用 JSON-lines 桥接到同一 run_workflow API。退出码 3 表示 pending_mapping/review_required，1 表示失败，不能把 3 当实机失败或通过。

桌面：类型选 ql5050px，源文件选统一 JSON 配置；选择 plan/assembly/bom/drawing/pipeline，输出填写尚不存在的目录，点击“加入 QL 任务”后开始队列。pipeline 必须有输出目录；CLI 的 --resume 可恢复相同流水线。parametric + QL-5050PX 现在路由到 QL plan，GT-ZX 必须显式选中，禁止混用。原生生成按钮仍用于旧三类零件；QL 路由只有离线任务，无隐式 COM 写入。

## 数据契约

统一配置：machine=QL-5050PX、units=mm、envelope、measurements、components、interfaces、mates、transmissions、drawing、sheet、jobs。components 指定 id/module/component_kind（editable/fixed/purchased）、part_number、material、quantity。接口指定 component_a/component_b/parameter_names/status/source。确认尺寸输入不等于确认原生映射；physical_mapping_register 始终先保持 pending_mapping，必须由 Gork 填真实文档/配置/特征/尺寸及来源。

workflow 输出参数计划、未知物理映射、装配问题、BOM、工程图模型、离线文件和批处理结果。原生配合/运动/精确干涉适配口为 workflow.NativeMechanicalPort；原生 SLDDRW/DXF 复用 control、native_exports、drawing_layout 的独占端口，不在云端执行。

## 统一测试矩阵（全部未测）

| 编号 | 调用/操作 | 预期 | 当前状态 |
| --- | --- | --- | --- |
| QL-01 | plan 默认配置 | 1800×900×1500 为目标；未知 OEM 为 null/pending | 未测 |
| QL-02 | 非 QL 配置输入 QL API | 拒绝；不读取 GT-ZX 默认模型 | 未测 |
| QL-03 | assembly 缺组件、无锚定、传动循环 | 输出具体问题；原生检查 unverified | 未测 |
| QL-04 | bom/drawing | CSV/JSON/SVG 非覆盖生成，编号数量材料一致 | 未测 |
| QL-05 | pipeline 与 resume | 依赖结果引用、失败继续、输出哈希复核 | 未测 |
| QL-06 | project.py batch + app.py | 相同 QL API；pending 传播；旧三类零件入口保留 | 未测 |
| QL-07 | 无 Windows 执行原生端口 | 明确拒绝，无 COM 附着 | 未测 |
| QL-08 | 源码交接包 | HEAD SHA、源码校验、dirty 信息、无未跟踪客户参数 | 未测 |
| SW-01 | Gork 真实 QL 映射/独立副本 | 逐项原生读回/重建/保存重开，证据完整 | 待真实模型 |
| SW-02 | 原生装配/运动/干涉与工程图 | 精确检查及原生文件打开，不能用 SVG/mock 替代 | 待 Windows |

## 源文件清单

- 参数/执行：src/ql5050px/parameters.py、control.py、workflow.py
- 装配/运动：assembly.py、workflow.py 中接口结构及原生检查端口
- 钣金：sheet_metal.py、panel.py
- 工程图/BOM：drawing_bom.py、drawing_layout.py、native_exports.py、bom_tree.py
- 制造队列：batch.py、manufacturing.py
- 统一入口：work/project.py、work/ql5050px.py、src/project_workbench.py、app.py
- 交接：work/prepare_ql_handoff.py、work/prepare_test_handoff.py、本文、examples/ql5050px_unified_config.json、examples/ql5050px_project_jobs.json
- 回归源码：tests/test_ql_workbench_contracts.py、test_framework_review_fixes.py（均未运行）

实际 commit SHA 由 prepare_ql_handoff.py 从 checkout HEAD 记录到 HANDOFF.json；本次集成 SHA 在 Issue #6 统一交接评论，不伪造自引用 SHA。GitHub 提交保存全部源码，打包器用于本地生成一份校验 ZIP，不需要逐模块通知 Gork。

## 已知缺陷/缺数据

真实 QL 原生装配、OEM 尺寸和范围、采购件规格/材料、接口坐标、SLDDRW 模板及完整 Windows transaction driver 均未提供。离线装配仍是自由度规则/AABB，复杂折弯/连续旋转碰撞、图纸剖视/公差、原生布局与注记绑定仍待实现/实机确认。第一、二批及框架审核记录中的其他问题沿用，不在本批展开排错。源码包中三个旧交接说明里的“尚未集成 PR #7”仅描述其历史批次，以本文和新入口为准。

回滚：保留三条功能分支；合并提交可用 git revert -m 1 <集成SHA> 撤回。只删除本批明确新建的离线输出，原生失败文件保留证据；不覆盖客户原始 CAD，不关闭未知 SW 会话。
