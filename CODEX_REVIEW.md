# Codex 审查清单 — solidworks-ai-v2 分支 wb/pending-features-offline

提交：`b014f54`（作者 WorkBuddy <workbuddy@local>，与仓库既有提交一致）
基线：HEAD = `271108e`，分支 `wb/pending-features-offline`

## 一、本次改了什么（7 文件，+855 / -22）

| 文件 | 行数 | 内容 |
|------|------|------|
| `src/solidworks_generator.py` | +283 | 释放槽/图纸残留/尖刺：`convert_border_hole_to_notch`、`_is_drawing_artifact_loop`（从 `feat/issue6-offline-tests` 移植） |
| `src/cad_analyzer.py` | +19 | 新增 `DrawingDimension` dataclass + `dimensions` 字段 |
| `src/turned_part.py` | +521 | 尺寸驱动车件引擎（从零写） |
| `tests/pending_features/*.py` | 各 +1 | 仅改 src bootstrap 路径 `parents[1]`→`parents[2]` |

## 二、验证现状（已实跑，未虚报）

- 36 个 pending 测试全过：`python -m unittest discover -s tests/pending_features`
- 全量回归零破坏：501 ran / 495 passed / **0 fail** / 6 skip
- **未做 SolidWorks 实机验证**，云通过 ≠ 实机通过（提交说明已注明）

## 三、重点审查项（按风险排序）

### 1. `turned_part.py` 尺寸驱动引擎（最高风险，从零写，+521 行）
**这是最需要你仔细看的部分。** 几何判断最容易出错。

- `_radius_ladder`：直径标注 → 半径档位，去异常值逻辑（`test_outlier_radius_is_dropped`）
- `_detect_bore` / `_tap_drill_diameter`：内孔识别 + 底孔直径推导（`test_long_thin_section_is_not_mistaken_for_bore` 这条边界很关键——长薄段会不会被误判成内孔）
- `_thread_depth`：螺纹深度读取（note 优先，回退到 bore）
- `_world_point`：草图坐标 → 模型空间映射
- **关键设计**：整条尺寸驱动路径只在 `analysis.dimensions` 非空时启用。请确认这条"隔离开关"是否真的无副作用——有没有可能某些带标注的正常图纸被误走新路径，或反之漏走。

### 2. `_is_drawing_artifact_loop` 误判风险
图纸残留检测（箭头三角形、零宽尖刺）本质是启发式。重点看：
- `test_small_but_real_hole_is_kept` / `test_three_mm_square_is_kept`：会不会把真实的小孔/小方块误删
- 阈值是否硬编码、是否与图纸单位（mm/inch）解耦

### 3. `convert_border_hole_to_notch` 边界
贴板边孔转缺口，重点看：
- `test_partial_edge_touch_is_kept_as_hole`：只部分贴边的孔必须保留为孔，不能误转
- 缺口方向（`test_border_notch_deepens_toward_panel`）

### 4. 移植来源的耦合
`solidworks_generator.py` 的 283 行是从 `feat/issue6-offline-tests` 分支 `git checkout` 移植的。请确认这些函数与当前分支其余代码（尤其 `apply_rectangular_relief_expansion`、`ensure_intersection_reliefs`、`generate_sheet_metal` 集成点）没有隐性依赖另一分支独有的东西。

## 四、已知未决（不在本次范围，供你决策）

- `work/` 目录下 7 个诊断脚本未跟踪未提交（`diag_*.py`、`retest_p248_fixed_panel.py`、`_write_*.py`），是之前排查 p248 折弯问题的残留，等你决定去留。
- 36 个 pending 测试仍未纳入主回归套件（`no __init__.py`），需显式 discover 运行。
- 本次改动**未推送远程**，仍在本地分支 `wb/pending-features-offline`。
