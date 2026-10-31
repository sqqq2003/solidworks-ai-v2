# 已审批决策转换

统一入口 `integrated` 现会在装配/传动规划之前转换决策。Linux 仅生成计划，不调用 COM。

```
python work/project.py ql --action integrated --config examples/ql5050px_approved_resize.json --output-dir runtime/approved-resize-new
python -m unittest discover -s tests -p test_decision_bridge.py -v
```

示例仅为合成尺寸：审批 `Length@Sketch1` 后，将 1 m 改为 1.8 m，输出 drive_plan 中的 1000→1800 mm 修改任务。总任务仍返回退出码 3，表示装配/OEM/工程图资料不全；单个尺寸任务就绪不代表整机可执行。

`approvals` 必须指定 parameter、document_id、dimension、reviewed=true 和 source；document_id 由扫描器的 path/configuration 稳定标识生成。`rules[document_id]` 使用 action=resize、targets={parameter: 新数值}，新数值沿用候选尺寸单位。多个候选可用明确审批选择唯一尺寸；重复审批拒绝。目标包络不会隐式当成每个零件的尺寸。

resize 从快照读取路径、配置和尺寸名，生成 drive.nodes、baseline 及 component bindings，并继续经过现有依赖图和保护检查。m 统一转 mm，角度保留 deg。生成参数名见 windows_tasks.decision_bridge.converted[].drive_parameter，可供已声明的传动依赖使用。尺寸缺失、采购件/固定件/保护接口、部分目标未批准时不生成该零件的修改；非有限值、重复原生目标或已有驱动绑定冲突会报错，避免覆盖已有任务。

translate 的 translation_mm 定义为装配坐标系中的**绝对位置** `[x,y,z]`，单位 mm，保留原旋转。还必须提供：

```json
{"execution_bindings":{"扫描document_id":{"assembly":"装配catalog键","occurrence":"children中的实例id","reviewed":true,"source":"实测/审核依据","allow_reposition":true}}}
```

实例引用的 source_path/configuration 必须与快照一致，并已有有效 transform_mm。对采购件、固定件和保护接口，决策规则及实例绑定都须明确 allow_reposition=true。该位置变更直接进入 assembly_plan 的实例变换/插入操作；不会把零件路径误当父装配的位置尺寸。多实例必须明确选择实例，不按文件名猜测。

keep 保持不变；manual_review、replace、regenerate 尚不自动生成原生操作，会列入 decision_bridge.pending_mapping。输出新增 decision-bridge.json，ZIP 和校验和包含该文件。windows_tasks.native_write_allowed 仍为 false，原生执行须完成整包映射与工程审核，使用原有独占 Windows 会话/隔离工作副本入口。此改动不包含新的 COM 适配，也未验证真实机器的运动、干涉或保存重开。
