# Issue #6 五模块第一版交接

本批次遵照 Issue #6 最后一段和用户本轮指令：只集中开发，不执行单元测试、集成测试、回归或 Windows 实机验证，不修复既有 Bug。不以之前分支的通过统计作为本批结果。基于 `dev/cloud-ai` 的 `e81438bbaf1fdbab09db125df115745f43a50b6c`，独立功能分支交付，不自动合并。

## 实际接口

| 模块 | 文件 / 入口 | 第一版功能 |
| --- | --- | --- |
| QL-5050PX 参数化 | `src/ql5050px/parameters.py:build_plan` | 机架、输送、左右驱动、封箱、安装接口、采购件；目标包络；确认输入和设计依赖求值；未知参数 pending |
| SolidWorks 自动控制 | `control.py:execute_variant` | 映射校验、拒绝未解析目标、模拟端口和 Windows 端口分流；复用现有差异计划、写入、重建、读回、SaveAs、重开、恢复和独占会话 |
| 装配/运动/干涉 | `assembly.py:inspect_assembly/sample_motion/interference` | 锚定连通性、配合类型规则、自由度估算、传动比传播/循环/多驱动检查、缺几何报告、平移采样和 AABB 干涉候选 |
| 钣金 | `sheet_metal.py:unfold_strip/generate_native/export_blank_dxf` | 复用 bend_allowance；外模线边长转切线直段、BA/BD/K、折弯区域检查、释放槽、带缺口展开 DXF；原生生成复用 solidworks_generator |
| 工程图/BOM | `drawing_bom.py`、`native_exports.py` | 稳定分组编号/材料/采购件/数量、CSV、工程图 JSON、毫米 DXF；原生 SLDDRW 视图创建和原生钣金 DXF 导出驱动 mixin |

公共长度使用 mm；采样时间 s；速度 mm/s；电机功率 W；折弯角 deg；原生绘图坐标转换为 m。`values_mm` 沿用现有事务契约的名称，具体单位必须读 `parameter_register`；v1 执行接口只接受 mm 长度映射，拒绝速度/功率/角度等不支持的原生写入。默认 1800×900×1500 仅为目标，不是 OEM 测量值。

## 调用入口（本批未运行）

仓库根目录：

```bash
python examples/ql5050px_batch.py --output results/ql5050px-first-run
PYTHONPATH=src python -m ql5050px parameters parameters.json
PYTHONPATH=src python -m ql5050px assembly assembly.json
PYTHONPATH=src python -m ql5050px sheet strip.json --output strip.dxf
PYTHONPATH=src python -m ql5050px bom components.json --output bom.csv
```

示例脚本串联五模块，所有几何和物料均明确为模拟夹具，控制模块使用空映射演示 pending 拒绝。CLI 的 JSON 参数分别对应 `build_plan`、`inspect_assembly`、`unfold_strip` 的关键字参数；BOM 输入为 `{"components": [...]}`。

Windows 实机接口：`execute_variant(plan, mapping_payload, destination, driver=owned_driver)`；必须通过已有 `sw_session` 的 task STA/独占会话，不能在 Linux 运行 COM。`driver` 必须实现已有 `ExecutionPort` 对应操作，尤其工作副本/引用隔离、已有目标拒绝、源路径别名检查、回滚和配置感知尺寸寻址。真实驱动和 OEM 映射由 Gork 接入，本包不虚构。

原生钣金生成：`generate_native(analysis, new_sldprt, generator_options={"profile_index": ..., "bend_indices": [...], "thickness_mm": ..., "radius_mm": ..., "angle_degrees": ...})`。可传已有 BendAllowanceSpec 及释放槽选项。原生展开：`control.export_native(port, {"model_path": isolated_part}, new_dxf, "flat_dxf")`。工程图：`export_native_drawing(port, request, new_slddrw)`。host driver 继承 `NativeExportsMixin` 并实现 `require_isolated_model`、`resolve_owned_model`；请求详见方法 docstring。没有归属/隔离证明时必须拒绝，不附着未知进程。

## 已知局限及待 Gork 验证事项

本批测试全部 **未测**，包括语法/导入检查、纯 Python 功能、示例、回归、原生 COM、SLDDRW/DXF 打开、制造正确性。没有实际执行发现的测试失败可报告。

1. 真实 QL OEM 文档、配置、特征、尺寸、材料和允许范围未映射；缺少数据时保持 pending。不得从 GT-ZX 搬用值。
2. 装配 DOF 是标量规则估算，不解约束雅可比；AABB 重叠只是候选，旋转、曲面和连续扫掠未实现。多条配合中混合 suppressed/active 时邻接处理需专项检查：抑制配合可能移除同对零件的有效连边。先记录，按要求不在本批排错。
3. 钣金只支持恒宽串联折弯带料；任意分支、斜折弯、冲压成形、孔与释放槽相交未实现。短段导致相邻释放槽重叠的情况需验证；当前不是可直接下料的制造批准。
4. ASCII DXF 写入器提供几何和单位；不含尺寸标注实体、字体、图框、投影视图求解。工程图 JSON 的 notes/BOM 未自动插入原生 SLDDRW；BOM CSV 独立输出。
5. NativeExportsMixin 是实际 API 调用实现但未在 Windows 验证：NewDocument、SaveAs3 的 pywin32 绑定形式、ExportToDWG2 的可选参数和模板设置可能需 Gork 调整。失败的新工程图保留供诊断；尚无导出事务回滚/重新打开验证。
6. 未实现完整 OEM Windows transaction driver；复用现有端口和事务实现，driver 由实机集成提供。新增代码不修改 Gork 正在测试的旧模块。

## 统一交给 Gork 的队列

先完成手头旧 GT-ZX/Step0 工作，再切换本批。建议先运行示例和纯接口，再接真实映射/driver，随后在独立副本验证小改型、重建、读回、保存重开、配合/运动/精确干涉，最后生成钣金和工程图/BOM。原始客户 CAD 不入仓库、不覆盖。记录失败参数、调用、SW 版本、返回码、文件和重现步骤，集中修复本批。

回滚：功能分支未合并时回到基线即可；合并后 revert 本批提交。删除仅由本批创建且明确归属的模拟输出；原生失败文件先保留证据，不能关闭或删除未知文档。提交 SHA 与交接链接在 Issue #6 统一评论，不逐模块触发测试。


## 后续补交：离线单测（feat/issue6-offline-tests）

上文“本批测试全部未测”指开发批次当时的范围；其后已在独立分支补 77 项离线测试并修复 7 项接口/边界缺陷，全量 448 ran / 441 passed / 0 failures / 7 skipped（Windows 本机，跨进程锁通过）。这些仍是纯 Python/mock 结果，**不代表 Windows 实机或机械验收**。矩阵、拒绝条件、skip/pending 与回滚见 `docs/issue6-offline-tests.md`。
