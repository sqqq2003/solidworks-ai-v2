# Issue #6：五模块离线框架（不实机）

基线 `79b95d723e33bbf0dd43df26f8b0ddec35ad1a91`，分支 `wb/issue6-five-modules-framework`。
本轮只搭**第一版可调用离线框架**：接口、mock、纯 Python 单测、最少可运行示例。
**不是** Windows SolidWorks 实机验收；任何报告里 `sw_live` 都是
`not_applicable_on_linux`，`cad_executed` 都是 `False`。

> GitHub Issue #6 原文本轮不可达（仓库私有 / 页面 404）。五模块定义以派发
> 任务 `TASK_issue6_framework_20261023_232204.md` 为准。

## 模块总览

| # | 模块 | 入口 | 状态 |
| --- | --- | --- | --- |
| 1 | QL-5050PX 参数依赖与配置 | `python -m src.ql5050px.cli` | framework |
| 2 | Windows SolidWorks 受控执行接口 | `src.sw_api.controlled.run_controlled_execution` | framework |
| 3 | 装配配合/自由度/运动/干涉预检接口 | `src.a01_next.assembly_precheck` | framework |
| 4 | 钣金折弯展开/释放槽/K 因子与生成接口 | `src.sheetmetal_unfold` | framework |
| 5 | 工程图、DXF 与 BOM 数据及导出接口 | `src.drawing_bom` | framework |

示例：`python examples/issue6_framework_demo.py`（synthetic，产物在
`runtime/issue6-demo/`）。测试：`python work/run_cloud_tests.py` 或
`python -m unittest tests.test_ql5050px tests.test_sw_controlled
tests.test_assembly_precheck tests.test_sheetmetal_unfold tests.test_drawing_bom`。

## 模块 1：QL-5050PX 参数依赖与配置

`data/ql_5050px_spec.json` + `src/ql5050px/`（config / graph / solver / cli）。

- **独立配置**：QL-5050PX 是只有 DWG 的封箱机，与 A01 / GT-ZX-1300 不是同一台
  装配；spec 里写死 `no_confirmed_dimensions_copied_from`，不照搬任何 GT-ZX
  已确认尺寸。
- **包络只是占位**：`target_envelope_is_placeholder: true`；1800×900×1500
  仅目标占位，`with_envelope()` 只搬数字，永远不把占位升级成已确认包络。
- **未知 OEM 保持 pending**：12 个 `pending_mapping` 节点全部留空并带
  `mapping_id`；保留接口（采购件、齿形齿距、板厚螺纹）在
  `interface_checks` 里全部 `preserve_unresolved`。
- 复用 `a01.py` 的预检原语与 `a01_parametric.constraints` 的通用校验；
  `a01.make_plan` 的三条机器无关 unresolved 原因在 solver 里改写成
  QL-5050PX 措辞，避免和 A01 结论混淆。
- 退出码：计划永远 `review_required`（有未确认/未映射量）时 CLI 返回 3。

## 模块 2：Windows SolidWorks 受控执行接口

`src/sw_api/controlled.py`。

- `ExecutionRequest(source, destination, plan, live, confirmed, sw_exe,
  mapping_payload)`。
- `refusals(request)` 显式列出全部拒绝条件：目标=源、目标已存在、mock 模式
  非 `.json` 后缀、live 模式的非 win32 / 无 COM / 未确认 / 缺映射 / 缺
  SLDWORKS.exe / 非 `.SLDASM` 工作副本。
- `run_controlled_execution(request)`：无拒绝时 mock 路径走既有
  `sw_api.apply.dry_run_apply`（只写 JSON trace，不写 CAD）；live 路径委托既有
  `sw_api.win32com_backend.apply_live`，本轮不提供 Windows transaction driver，
  Linux 上连 COM 都不会 import。
- 被拒绝是**成功的诚实回答**：报告 `status=refused` 且带原因，
  `cad_executed` 恒为 False。

## 模块 3：装配配合/自由度/运动/干涉预检接口

`src/a01_next/assembly_precheck.py`（既有 `mate_check.py` 不动）。

- `dof_report(components, mates)`：按**简化 DOF 表**核算自由度（教学模型，
  非 SW mate 求解器）；未建模配合类型标 `not_modeled`，过约束标
  `redundant`，`dof` 不为负。
- `motion_check(report, sweep_degrees)`：只校验扫掠参数范围，不模拟运动，
  `motion_verified` 恒 False。
- `interference_check(parts)`：AABB 包围盒粗筛，`exact_interference` 恒
  False。
- `MockMechanicalCheckPort` 实现 `sw_api.transaction.MechanicalCheckPort`，
  供测试与离线规划。
- 全部报告带 `mates_solved=False` / `sw_live=not_applicable_on_linux`，
  不宣称真实运动/干涉检查。

## 模块 4：钣金折弯展开/释放槽/K 因子与生成接口

`src/sheetmetal_unfold.py`。

- `unfold_plan()`：BA / BD / OSSB / K 与展开长，全部来自既有
  `bend_allowance`；同时产出可写入 SW 的 `BendAllowanceSpec` 数据
  （`sw_type` 对齐 `swBendAllowanceTypes_e`）。
- `unfold_chain()`：等参数多折弯，`sum(segments) - sum(BD)`。
- `relief_plan()`：槽宽 `max(t, 0.5)`、中心线深度 `t + R + 0.5`、扩槽级差，
  全部来自既有 `solidworks_generator` 助手（依据见 `src/BEND_RELIEF.md`）。
- `generation_request()`：只**描述**对既有
  `solidworks_generator.generate_sheet_metal` 的调用（经
  `a01_next.sheet_metal_hook` 委托），`called=False`，不执行、不复制第二套
  生成器。

## 模块 5：工程图、DXF 与 BOM 数据及导出接口

`src/drawing_bom.py`。

- `bom_from_sheet_jobs()`：复用 `batch_export.SheetPartJob` 与
  `format_sheet_part_name`；厚度来自图纸注释，显式传入的界面默认会标来源，
  拿不到厚度就进 `unresolved`，不借数。
- `bom_from_variants()`：复用 `roller_spec.spec_from_variant` /
  `variant_label`。
- `bom_from_parametric_plan()`：缺模型时的 mock BOM，按子系统一行，包络按
  占位呈现。
- `write_bom_csv()` / `bom_csv_rows()`：纯数据 CSV（不是 CAD/工程图产物）。
- `export_plan()`：mock 导出只写 JSON trace，拒绝 `.dxf/.dwg/.slddrw` 等
  产品文件后缀与 `backend=live`；`dxf_written` 等恒 False。
- `drawing_hints_for_bom()`：复用 `drawing_notes.read_drawing_hints`。

## 诚实边界

- 未跑 = 未测：每个报告字段如实标注；mock 与原生分开写。
- 不启动/接管 SolidWorks；不写桌面；不改母机 CAD、`D:\工程\...\程序`、客户
  图纸。
- 本轮发现的既有缺陷只记入输出目录 `KNOWN_ISSUES.md`，不深挖。
