# 装配配合几何约束分析（约束秩 / 自由度 / 冗余）

`engineering_intelligence.assembly`（命令 `assembly`）原来只按配合类型查表扣自由度（同心=4、重合=1……）。这种标量估算有两个问题：

- 识别不出冗余。两个同轴的同心配合会被算成扣掉 8 个自由度、判为"完全固定"，但滚筒其实还能沿轴向滑动。
- 说不出具体还剩什么运动。只给一个数字，不知道是转动还是平移、绕哪根轴。

现在每个配合可以带上它在**当前位姿**下绑定的几何（点、轴、面，装配坐标系，mm）。模块据此计算约束对零件微小位移的梯度，用秩分析得到：

- 整个装配的瞬时自由度（mobility）；
- 每个活动零件还剩下的平移方向、转动轴线（轴线位置和螺距）；
- 冗余配合：同一对零件之间的多余配合，以及跨零件回路的过约束；
- 声明位姿与配合不符的配合（相当于 SolidWorks 的配合错误）。

这只是对调用方声明几何的一阶分析，不是 SolidWorks 配合求解、运动算例或干涉检查。结果始终 `engineering_approved=false`、`native_status=pending_windows_validation`。

## 调用

```bash
python work/engineering_intelligence.py assembly examples/issue50-assembly.json
```

API：`engineering_intelligence.run_module('assembly', request)`。只做几何秩分析可直接调用 `engineering_intelligence.mate_rank.analyse_constraints(components, mates)`。

示例 `examples/issue50-assembly.json` 是合成滚筒：机架固定，滚筒同心 + 轴肩端面距离 5 mm。输出 `constraint_rank.mobility=1`，滚筒只剩绕 X 轴（过原点）的转动。因为没有原生读回，整体状态仍是 `review_required`。

## 输入

只要有一个未压缩的配合带 `geometry`，就启用几何分析。这时其余未压缩配合也必须都有 `geometry`（`fixed` 配合除外）。缺少几何或类型不受支持时，退回原标量估算，并在 `issues` 里写明原因（`constraint_rank_geometry_missing:<id>` / `constraint_rank_unsupported_mates:<id>`），不做半套分析。

```json
{
  "id": "axial", "a": "frame", "b": "roller", "type": "distance",
  "geometry": {
    "unit": "mm", "source": "SW 读回或图纸，写明来源",
    "a": {"kind": "plane", "point_mm": [0, 0, 0], "normal": [1, 0, 0]},
    "b": {"kind": "plane", "point_mm": [5, 0, 40], "normal": [-1, 0, 0]},
    "distance": {"value": 5, "unit": "mm", "source": "设计间隙"}
  }
}
```

- 实体 `kind`：`point`（`point_mm`）、`axis`（`point_mm` + `direction`）、`plane`（`point_mm` + `normal`）。方向会归一化，可正可反。
- `geometry.unit` 必须是 `mm`，`geometry.source` 必填。距离用 `distance`（mm），角度用 `angle`（deg），都要带 `value/unit/source`。
- 零件可声明 `expected_dof`（整数）和/或 `expected_motions`：
  - `{"type": "rotation", "axis_point_mm": [...], "direction": [...]}`
  - `{"type": "translation", "direction": [...]}`
- 可选 `linear_tolerance_mm`（默认 0.01）、`angular_tolerance_deg`（默认 0.01），用于判断声明位姿是否满足配合。

支持的配合与实体组合（a、b 顺序不限）：

| 类型 | 实体组合与约束方程数 |
|---|---|
| fixed | 不需要几何，6 |
| coincident | 面-面 3、点-面 1、点-点 3、点-轴 2、轴-面 2、轴-轴 4 |
| concentric | 轴-轴 4、点-轴 2 |
| distance | 面-面 3、点-面 1、轴-面 2、点-点 1、点-轴 1、轴-轴 3 |
| parallel | 面-面 2、轴-轴 2、轴-面 1 |
| perpendicular | 面-面 1、轴-轴 1、轴-面 2 |
| angle | 面-面 1、轴-轴 1；0° / 180° 退化，请改用 parallel |

齿轮、凸轮、宽度、相切等其他配合尚不支持，会退回标量估算。

## 输出 `constraint_rank`

| 字段 | 含义 |
|---|---|
| `mobility` | 整个装配的瞬时自由度 = 6 × 活动零件数 − 秩 |
| `components[].dof` | 该零件相对地面还能动的维数。机构耦合时（如四连杆）各零件 dof 之和可大于 mobility |
| `components[].translations` | 可平移的单位方向 |
| `components[].rotations` | 可转动的轴线：`direction`、`axis_point_mm`（轴线上离原点最近的点）、`pitch_mm_per_rad`（非 0 为螺旋运动） |
| `pair_redundant_equations` | 同一对零件之间重复的方程数。同心 + 端面重合共用的方向约束属于正常建模，只统计不报问题 |
| `mates[].removable_within_pair` | 删掉这个配合，这对零件之间的约束不变（重复配合、两端同轴的第二个同心等） |
| `loop_redundant_equations` / `loop_mates` | 跨零件回路的过约束数量和涉及的配合，例如用空间转动副搭的平面四连杆会多出 3 个 |
| `mates[].residual` | 声明位姿下的配合残差（mm / deg） |

所有固定零件视为同一个地面，所以两块固定侧板上的两个轴承同心，也按"同一对零件的多余配合"报。

## 状态规则

| 条件 | 结果 |
|---|---|
| 残差超过容差 | failed：`mate_geometry_unsatisfied:<id>` |
| 自由度与 `expected_dof` 不符 | failed：`constraint_dof_mismatch:<id>` |
| `expected_motions` 中的运动被约束住 | failed：`expected_motion_blocked:<id>` |
| 实际可动维数多于 `expected_motions` | failed：`unexpected_free_motion:<id>` |
| 同一对零件存在可删除配合 | review_required：`redundant_mates:<a>/<b>:<ids>` |
| 回路过约束 | review_required：`overconstrained_loop:<数量>:<ids>` |
| 零件可动但没有声明期望 | review_required：`free_motion_unreviewed:<id>` |
| 两个固定零件之间的配合 | review_required：`mate_between_fixed_components:<id>` |

启用几何分析后，标量估算里的 `dof_mismatch`、`possible_redundancy`、`estimated_nonzero_DOF`、重复签名提示不再进入 `issues`（`offline` 字段里仍保留原始结果）。`native_readback` 的摘要包含 `geometry`，几何改动后旧读回会判为 `stale_native_readback`。

## 限制

- 一阶（瞬时）分析：奇异位姿（死点、共线）可能多出瞬时自由度；不判断大位移下的可达性。
- 最多 60 个活动零件、600 个约束方程，超出请拆子装配。
- 几何必须由调用方提供，可来自 SolidWorks 读回或图纸；模块不读 CAD 文件，不连接 SolidWorks。
- 不做干涉和运动包络；干涉仍是 `ql5050px.assembly` 的轴对齐包围盒候选。
