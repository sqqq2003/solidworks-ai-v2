# Issue #9 三模块统一交接

## 本批功能

- 自动装配：assembly_builder.py 提供 QL 专用装配树、子装配/实例、刚体变换校验、装配拓扑、差异、配合参考和缺映射清单。native_machine.py 提供 readonly Pack and Go、原生模板/已有零件复用、已有 sheet 生成器委托、插入/替换、配置、定位、固定、命名配合更新、重建、保存重开和引用隔离核对。
- 传动联动：drive_variant.py 提供无 eval 的尺寸/运动依赖图，包络影响传播、传动比、中心距、开口带长近似、理论链节数、带速、安装位置/行程、范围与比较约束、固定件/采购件保护、逐零件/配合修改计划。Windows adapter 提供配置限定尺寸写入、读回、配合更新，以及离散运动采样、原生配合状态和干涉证据采集。
- 制造工程图：manufacturing_drawings.py 从装配树/BOM/工艺参数生成零件及装配图清单、编号、材料/板厚/工艺与待确认基准/公差。native_drawings.py 复用原生导出/注记模块，调用原生模型/投影/展开视图、关联尺寸、注记、关联 BOM、序号球、图框/比例/mm 单位、SLDDRW 保存重开与钣金 DXF。
- 统一入口：machine_package.py 产生包络→装配→传动→工程图/BOM→OEM缺参/实机测试包；现有 project.py、app.py、project batch、QL BatchRunner 均添加入口。保留旧功能，不执行任何隐式原生操作。

## 调用（未测试）

```bash
python work/project.py ql --action auto_assembly --config examples/ql5050px_issue9.json
python work/project.py ql --action drive --config examples/ql5050px_issue9.json
python work/project.py ql --action manufacturing --config examples/ql5050px_issue9.json
python work/project.py ql --action machine_package --config examples/ql5050px_issue9.json --output-dir runtime/issue9-new
python work/project.py batch examples/ql5050px_issue9_jobs.json
python work/build_issue9_delivery.py --config examples/ql5050px_issue9.json --out runtime/issue9-delivery-new
```

桌面类型选 ql5050px，配置选上述 JSON；动作选 auto_assembly/drive/manufacturing/machine_package，加入 QL 任务。交接包动作必须填写新输出目录。原生执行需要另行调用 Windows API，GUI/CLI 上述动作仅规划与打包。

公开 API：plan_assembly/execute_assembly、plan_drive/execute_drive、plan_drawings/execute_drawings、plan_machine/write_machine_package。原生显式入口：`run_owned_native(sw_exe,new_work_root,operation,payload)`；operation 为 assembly、drive、drawings、checks。装配/传动 payload 分别为已消除 pending/conflict 的计划；drawings 为 `{plan,assembly_receipt}`（先再次隔离输入模型）；checks 为 `{document,configuration,motion_samples}`。也可在同一已证明归属 STA 内使用 ManufacturingDriver(lease,work_root) 串联操作。禁止直接在 Linux 使用驱动。

生成的 gork-execution-package.zip 包含原始配置、整机/装配/传动/工程图计划、BOM CSV、OEM映射缺失项、统一矩阵、SHA256 和源码版本字段。该 ZIP 不含客户 CAD，不是已生成的原生整机；源码由本批 Git 提交及源码增量包提供。主提交 SHA 另记 Issue #9 交付评论，避免自引用伪 SHA。checkout 下打包命令自动记录真实 HEAD。

## 验收与缺陷边界

所有单测、全面回归、GUI点击、SW原生测试均**未测**。本批仅允许语法/导入自检与生成交接文件，生成计划/ZIP不是功能测试通过。

1. 所有 OEM 路径、尺寸、配置、安装/配合引用、模板、行程、材料/工艺/公差方案缺值均 pending，示例明确 synthetic；不能拿 GT-ZX 填充。未映射时拒绝执行原生计划。
2. Native API 签名与 pywin32 返回形式未在 Windows 核对。重点核对 SavePackAndGo、AddComponent5/ReplaceComponents2、AddMate5、配置限定 SetSystemValue3、InsertBomTable4、BOMBalloon2、展开视图与 DXF 参数。Save3/命名变化/投影父视图行为需 Gork 集中验证。
3. PnG 当前采用平铺工作目录并拒绝重名依赖；虚拟零件/外部引用/被抑制原件可能被拒绝。完整的配置差异、配合替换后重绑定与失败自动回滚未实现；失败保留工作目录/会话证据，不能改原件。
4. 传动公式是声明的机械设计规则，带长和链节数是理论/近似值；不自动选择标准带/链型号、偶数链节、预紧、负载/强度或无损伸缩。单位由图节点声明，尚无完整量纲推导。受保护件只能显式允许位置变化。
5. Native 检查返回原始 mate 状态与离散驱动样本，不是连续动力学/运动学求解或整机机械批准。原生干涉 API 无结果与异常处理、配合状态枚举含义需实机核对。
6. 工程图不会伪造基准/公差。当前以引用实体生成关联尺寸并保留工艺/公差方案数据，尚未实现全部 GD&T符号/剖视/自动排版/公差自动写入；原生BOM与计划编号一致性待核验。图框/比例/图层和投影规范必须人工确认。制造批准始终 false。
7. 本批不处理旧普通 Bug。统一测试矩阵位于交接包 test-matrix.json，包含 ASM/DRV/DRW/PKG；Gork 先继续旧 p248，再整批测试修复，不逐模块切换。

回滚：独立功能分支保留；合并时可 revert 本批提交。仅删除明确新建离线输出；原生副本保留失败证据，不关闭未知会话、不覆盖原始 CAD。
