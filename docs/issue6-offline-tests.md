# Issue #6 五模块离线测试矩阵与交接

范围：只证明纯 Python / mock 契约与拒绝条件，**不证明 SolidWorks 实机**。未运行 COM、未生成 SLDPRT/SLDDRW、未接触客户 CAD。

- 基线：`13cc10c2a4fb29cbe166b16f82c9a72b7896ea0a`（`feat/issue6-ql5050px-five-modules`）
- 测试分支：`feat/issue6-offline-tests`
- 测试提交：`3b3013a86b03548f539a6e4490df3a1b24a47f74`（Qoder Agent，本地未推送）
- 第二轮：`ebb09e2`（原生生成校验顺序，Linux CI 少 2 个 skip）
- 验收步骤与期望输出见 `docs/issue6-acceptance-checklist.md`

## 运行

```bash
python -X utf8 work/run_cloud_tests.py
python -m unittest discover -s tests -p "test_ql5050px*.py"
python examples/ql5050px_batch.py --output <新目录>
```

## 本机结果（Windows 10 / Python 3.14.7）

- 全量：**448 ran / 441 passed / 0 failures / 0 errors / 7 skipped**，跨进程写锁通过。
- 本文之后的 P0 重建（见 `TASK_STATUS.md` 的 `P0-QODER-001`）把 14 项 pending 合约移入回归，仓库全量变为 **473 ran / 466 passed / 0 failures / 0 errors / 7 skipped**（含 11 项重建守护测试），pending 剩 22 项；本文件其余数字仍指本轮 issue6 提交当时的状态。
- 新增 QL-5050PX：**77 项，全部通过**（其中 1 项按平台跳过）。
- `solidworks_live_verified=false`；`sw_live=not_applicable_on_linux` 语义不变。
- 纯净克隆复跑 `ebb09e2`：结果与提交的 `results/cloud/latest.json` 逐字节一致，提交树自身可复现。
- 版本兼容静态检查：`ast.parse(feature_version=(3,11)/(3,12))` 扫描 114 个 `.py`，0 处不兼容；本机 `ezdxf` 与 `requirements-cloud.txt` 同为 `1.4.4`。
- 本机只有 Python 3.14.7，**未在 3.11/3.12 上实跑**；Linux CI（`.github/workflows/cloud-tests.yml`，Python 3.11/3.12）运行同一套件，平台相关跳过数量会不同。CI 仅在 push 到 `dev/cloud-ai` 或手动 `workflow_dispatch` 时触发，本分支未 push 故 CI 尚未运行。

## 测试矩阵

| 模块 | 测试文件 | 覆盖 | 明确拒绝 / 边界 | 明确未测 |
| --- | --- | --- | --- | --- |
| 参数依赖 | `tests/test_ql5050px_parameters.py` | 默认包络仅 `target_only`；模块参数全 pending；确认输入/未确认输入；设计关系推导前后框与左右驱动；有符号 `left_drive_x`；映射模板可加载 | 非正数、bool、字符串、NaN/Inf 包络；未知参数；非正推导长度；模板不产生 `mm/s`/`W` 非法单位 | 真实 QL OEM 尺寸、材料、允许范围 |
| 受控执行 | `tests/test_ql5050px_control.py` | QL/mm 合约；无可写映射返回 pending；mock 事务 `simulated_pass` 且 `cad_executed=false`；失败恢复；导出必须位于 writer 租约内 | 未解析目标；非 mm 单位；mock 未声明 simulated；越界值；Linux/无驱动；错误后缀/已存在文件/未知导出类型 | Windows 驱动、COM 写入、readback、SaveAs、重开 |
| 装配/运动 | `tests/test_ql5050px_assembly.py` | 锚定连通、DOF 估算、冗余提示、传动比传播、AABB 重叠/间隙预警、缺失几何、采样平移 | 重复 id、非法配合/移动件、传动环与多驱动、非法 AABB、bool/负数间隙、非有限采样 | 约束雅可比、真实配合求解、连续扫掠、SW 运动 |
| 钣金 | `tests/test_ql5050px_sheet_metal.py` | 串联折弯展开长度（与外模线公式对照）、折弯线中心、释放槽默认/自定义、DXF 层与单位、示例入口；原生生成的参数拒绝在两个平台都实跑 | 腿长不足、角度数量/数值非法、t/R/K 非法、释放槽过小/过宽、覆盖已有 DXF、非 Windows 原生生成、错误后缀、重复 `output_path` | 原生折弯特征、重开、展开实体、DXF 导出的实机结果 |
| 工程图/BOM | `tests/test_ql5050px_drawing_bom.py` | BOM 分组/数量/实例/采购件；缺失材料保持 pending；CSV/JSON 往返；DXF 坐标与层校验；工程图模型 `unverified` | 数量非正整数、零件号不稳定、材料/配置非字符串、非法尺寸、非法 DXF 坐标/层、覆盖已存在文件 | 原生 SLDDRW 视图、标题栏、模板、真实 BOM 物料 |
| 入口/示例 | `tests/test_ql5050px_cli.py` | `python -m ql5050px` 四子命令；示例产物齐全且状态为 `offline_simulation_only` | 未知子命令退出码 2；输出文件拒绝覆盖；示例拒绝已存在目录 | GUI、桌面点击、批量任务调度 |

## 本轮修复的接口缺陷

1. `sw_api.mapping.mapping_template()` 直接用于 QL 计划时会生成 `mm/s`、`W` 行并被 `load_mappings()` 拒绝；现只输出 v1 schema 可表达的单位，其余仍留在计划 `pending_mapping`。
2. 同一对零件同时存在有效与抑制配合时，抑制配合会删除有效连通边；现仅有效配合参与邻接。
3. BOM 中 `configuration: null` 与 `""` 混用会在排序时抛 `TypeError`；现统一归一化并校验字符串类型。
4. `left_drive_x` 设计上为负值，确认输入却被正数校验拒绝；现对有符号参数使用有限数校验。
5. `interference(..., clearance_mm=True)` 被当作 1 接受；现拒绝 bool。
6. `export_native(..., kind=...)` 未知类型从 `KeyError` 改为 `ValueError`。
7. `execute_variant()` 的 `pending_mapping` 曾混入 `target_*` 包络；现与计划未解析集合一致，目标值不再被标成 OEM 待映射。
8. 本机有 COM 运行时，`test_live_flag_is_refused_without_com` 的平台假设不成立；现按 COM 可导入性跳过，并新增“有 COM 无映射时退出码 1”的配对测试（Linux 仍保留退出码 2 覆盖）。
9. `sheet_metal.generate_native()` 的参数拒绝排在平台拒绝之后，Linux CI 只能跳过“已存在/错误后缀”和“重复 `output_path`”两项；现先校验参数、再拒绝非 Windows，拒绝条件全部保留，Linux 上这 2 项转为实跑（`ebb09e2`）。

## skip / pending

- 平台跳过（本机 2 项）：`test_live_flag_is_refused_without_com`（存在 COM）、`test_refuses_off_windows`（Windows 分支）。Linux 上这 2 项分别改为实跑 COM 缺失拒绝与 Windows 拒绝，且 `ebb09e2` 之后原生生成的 2 项参数拒绝在 Linux 也实跑。
- 以进程内 `sys.platform` 补丁模拟 Linux 分支已核验拒绝行为，但**属于模拟，不是 Linux 实机证据**。
- 基线既有跳过 5 项：DWG 转换器、LibreDWG、缺失上传样图、原始基线哈希、Linux 写桥拒绝。
- `tests/pending_features/` 36 项原始特征合约仍未实现，不计通过。
- 未测清单：Windows 受控执行、原生钣金特征、SLDDRW/DXF 原生导出、真实 OEM 映射、p248 实机闭环。

## 回滚

- 未合并：回到基线 `13cc10c` 即可；本测试分支可整体丢弃。
- 已合并：revert `3b3013a`、`8244319`、`ebb09e2` 三个提交。
- 未修改客户 CAD、D 盘程序或其他执行者的工作副本。

## 交接

- **Gork**：先按 `--sw-exe` 正式独占会话核验拒绝条件，再接真实映射/驱动；p248 仍以 Issue #5 为准。
- **Codex**：复核 `mapping_template` 过滤与 `execute_variant` 的 `pending_mapping` 归一化是否与 A01 轨道一致。
- 本文件所有“通过”仅指离线测试，不得写成 SolidWorks 实机通过。
