# 钣金展开 DXF 下料直出（#49 第一阶段 F2）

离线模块，纯 Python 标准库。输入一份 feature_tree 展开报告
（status ok）加每弯一份显式工单记录，输出激光切割可直接用的
ASCII DXF（R12）加折弯顺序卡（JSON）。

## 调用

```bash
python -m flat_dxf.cli flat_dxf/examples/unfold_sample.json \
    flat_dxf/examples/job_sample.json --out-dir out
```

退出码（与模块 ③④ 同款约定）：

* 0 = DXF 通过；
* 1 = 工单 pending（bend_card.json 仍写出 pending 报告）；
* 2 = 输入错误（文件缺失、JSON 坏、形状不对、板宽非法）。

输入文件永不被修改；输出只写进 `--out-dir`（flat.dxf +
bend_card.json）。

## DXF 图层

* `CUT`：展开轮廓（矩形，长 = 展开长，宽 = 显式板宽）；
* `BEND`：折弯线，位于每个折弯区中心，横贯板宽；
* `NOTES`：折弯标签（顺序号、方向、角度）与展开长注记。

单位：HEADER 中 `$INSUNITS = 4`（mm）。DXF 内文字只用 ASCII，
工单原文（含中文工艺名）只进 bend_card.json，不进 DXF。

## 工单记录（每弯必填，缺失即 pending）

`bend_id`、`thickness_mm`、`radius_mm`、`angle_degrees`、
`k_factor`、`v_opening_mm`、`process`、`direction`（up/down）、
`sequence`（整数，唯一）。另需顶层 `blank_width_mm`（> 0）。

**t / K 铁律**：板厚、内 R、下模 V 口、角度、K、工艺一律按
每单输入计算；缺失 → pending_confirmation，绝不设默认数。
展开长只作派生对照：DXF 排布由报告的直线段与重算的 BA
拼出，总长须与报告的展开长在 1e-9 内一致，否则 pending，
不偏向任何一方；每弯 BA 也与报告逐弯核对（1e-9）。

## 排布约定

一条带料 n 折对应 n+1 段直线；段数不符即 pending，不补段。
折弯线位于折弯区中心；折弯顺序按 `sequence` 排。

## 未测清单（全部 pending_windows_validation）

* 激光切割实机读图与切割；
* 折弯机实机折弯（方向、角度回弹）；
* SW2022 / SW2025 行为。
