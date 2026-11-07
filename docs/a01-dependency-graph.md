# A01 依赖图

尺寸单位以 `data/machine_spec.json` 的 `units: mm` 为准。`count` 只出现在尚未映射的个数上，没有数值。边的代码对照是 `src/a01_parametric/graph.py` 里的 `DOCUMENTED_EXTRA_EDGES`。

## 机架 frame

这些边在 `parameter_graph`，由 `a01.make_plan` 计算。

| 下游 | 依赖 | 规则 |
| --- | --- | --- |
| frame_length | length, front_allowance, rear_allowance | 目标长减去前后余量。余量未确认则为空 |
| frame_width | width, left_allowance, right_allowance | 目标宽减去左右余量。余量未确认则为空 |
| column_height | height, top_allowance, bottom_allowance | 目标高减去上下余量。余量未确认则为空 |

## 输送 conveyor

| 下游 | 依赖 | 规则 |
| --- | --- | --- |
| conveyor_bed_length | frame_length | copy。通用规则，随机架内长，不是滚筒实测 |
| conveyor_clear_width | frame_width | copy。通用规则，随机架内宽 |
| passline_height | column_height | pending_mapping `A01.conveyor.passline_height` |
| roller_pitch | conveyor_bed_length | pending_mapping `A01.conveyor.roller_pitch` |
| roller_count | roller_pitch | pending_mapping `A01.conveyor.roller_count` |

## 传动 drive

| 下游 | 依赖 | 规则 |
| --- | --- | --- |
| drive_center_along_length | conveyor_bed_length | pending_mapping `A01.drive.center_along_length` |
| chain_pitch | drive_center_along_length | pending_mapping `A01.drive.chain_pitch`，保留齿形、齿距及传动接口 |
| sprocket_teeth | chain_pitch | pending_mapping `A01.drive.sprocket_teeth`，保留同一接口 |
| bearing_journal | frame_width | pending_mapping `A01.drive.bearing_journal`，保留轴承配合与轴颈接口 |

## 安装位置 mount

| 下游 | 依赖 | 规则 |
| --- | --- | --- |
| motor_mount_x | drive_center_along_length, frame_length | pending_mapping `A01.mount.motor_x`，保留电机、轴承等采购件尺寸 |
| motor_mount_z | column_height | pending_mapping `A01.mount.motor_z`，保留同一采购件接口 |
| bearing_mount_span | frame_width, bearing_journal | pending_mapping `A01.mount.bearing_span`，保留轴承配合与轴颈接口 |
| sheet_thickness | frame_length | pending_mapping `A01.interfaces.sheet_thickness`，保留板厚和螺纹规格 |
| thread_major_diameter | sheet_thickness | pending_mapping `A01.interfaces.thread_major_diameter`，保留同一规格接口 |

未映射清单就是上表所有 `pending_mapping`。求解器不给它们填数。
