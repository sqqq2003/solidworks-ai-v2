# 几何 IR（geometry-ir/1）

特征树到桥接 build 的几何传输格式。它补上桥接 CONTRACT.md §12
留下的诚实缺口：§12 的 build 过去只用 `plan_id` 引用已验证计划，
消息里不传完整几何；本 IR 就是那份几何——版本化、单位显式、
每单参数必填。

## 格式（geometry-ir/1）

```json
{
  "format": "geometry-ir/1",
  "units": "mm",
  "angles_unit": "degrees",
  "source": {"tree_name": "...", "tree_version": "feature-tree/1",
             "units": "mm"},
  "features": [
    {"id": "sketch-1", "type": "sketch", "depends_on": [],
     "sources": [], "status": "confirmed", "pending_reasons": [],
     "params": {"points": [[0, 0], [116, 0], [116, 60], [0, 60]]},
     "geometry": {"points": [...], "closed": true, "segments": [...]}},
    {"id": "bend-1", "type": "bend", "depends_on": ["sketch-1"],
     "params": {"thickness_mm": 2.0, "radius_mm": 1.5,
                "angle_degrees": 90.0, "k_factor": 0.38, "...": "..."}}
  ],
  "execution_order": ["sketch-1", "bend-1", "..."],
  "derived": {"derived_not_input": true, "...": "..."}
}
```

* 特征类型与 feature_tree 的 SUPPORTED_TYPES 一致：sketch /
  extrude / hole / bend / sheetmetal / check / fillet / chamfer /
  revolve。fillet / chamfer 在树里同样是占位，IR 照单全收，
  校验时标 pending_not_executable，绝不谎称可执行。
* 草图几何：`points`（[x, y]，mm）+ `closed`（默认 true）+
  由点列展开的 `segments`（闭合时含收尾段）。弧 / 圆草图实体
  尚未建模，见未实现项。
* 参数全部原文照搬：不改名、不四舍五入、不补默认值。
* `derived` 只作校验对照：每弯 BA/BD、整件展开长、回转体积。
  删掉 `derived` 再校验，结论必须不变；build 请求绝不读它。

## 每单参数口径（硬规则）

t / R / 角度 / K 全部按该单输入：缺失 → pending_confirmation，
绝无默认值。示例里的 t=2.0 / R=1.5 / K=0.38 / 90° 只是示例
输入值，不是默认值、不是推荐值。

## 调用

```bash
# 只出 IR 与校验结论
python -m geometry_ir.cli tree.json --out-dir out
# 同时出 CONTRACT.md §12 build 请求（四项缺一不可；缺 flip
# 方向不给默认值，直接按输入错误退出）
python -m geometry_ir.cli tree.json --out-dir out \
  --title part.SLDPRT --part-path staging/part.SLDPRT \
  --plan-id plan-1 --flip-direction false
```

退出码：0 = IR 有效且无 pending（要求 build 时请求已写出）；
1 = 结构有效但有 pending，或 build 请求被扣下；
2 = 输入错误（读不懂的 JSON、畸形树、非法的 flip 方向值）。
输入文件永不修改，只写 `--out-dir`。

Python 调用：

```python
from geometry_ir import tree_to_ir, validate_ir, to_build_request, mock_roundtrip
ir = tree_to_ir(tree_dict)
report = validate_ir(ir)  # {"ok", "errors", "pending", ...}
request, report = to_build_request(
    ir, title="part.SLDPRT", part_path="staging/part.SLDPRT",
    plan_id="plan-1", flip_direction=False)
result = mock_roundtrip(tree_dict)  # 需要 feature_tree 在 sys.path 上
```

## 与 §12 build 请求的对齐

`to_build_request` 产出的键与 §12.1 的 params 一一对应：
plan_id / title / part_path / thickness_mm / radius_mm /
angle_degrees / k_factor / flip_direction / bend_count /
idempotency_key / units（"mm"）。幂等键按 §12.4 由调用方
确定性生成：sha256("<plan_id>:S1:build")。

以下情况请求一律扣下，列出 pending，不猜不凑：

* 校验有 error 或 pending；
* 树里没有折弯（不是钣金 S1 的活）；
* 各折弯的 t/R/角度/K 不完全一致（不挑其中一弯的值顶替）；
* 树里含 extrude / revolve / fillet / chamfer（不是钣金件，
  不能走 §12 的钣金 build）。

## 与现有模块的关系

* feature_tree/（#36 已合并 + #44 补齐）：IR 的唯一输入来源；
  序列化不改树语义，执行顺序用同样的 Kahn 依赖序。
* csharp-bridge/CONTRACT.md §12（#32 已合并）：本包只对齐它，
  不改它原有章节；对齐说明写在这里，不重写已合并契约。
* dxf_extract/（#35 已合并）：计划 → 特征树 → IR 是同一条链；
  IR 不直接消费 DXF 计划，revolve 同样不从计划转换。
* offline_verify/（#38 已合并）：本包新增测试会被其运行器发现；
  基线期望数差异（若有）另行送审，绝不顺手改基线。

## 未实现项

* 草图弧 / 圆实体：目前只传点列与闭合位；带弧的草图轮廓
  仍需显式弧段表达，待后续批次。
* C# 侧 IR 接收与 RealSwApp build：本包只有 Python 侧序列化、
  校验与 mock 往返；命名管道上传输 IR、实机建模均待 Windows
  验收，标 pending_windows_validation。
* 装配级 IR：只覆盖单件特征树；整机装配关系不在本格式内。

## 给 Gork 的验收增补

* IR1. 同一棵树：IR 里的特征顺序、依赖边、草图点列与树 JSON
  逐项一致；mock 执行顺序服从 IR 的 execution_order。
* IR2. 同一棵钣金树：IR 派生 BA 与 mock 读回 BA 比对（容差 1e-9）；
  展开长与 feature_tree unfold 报告比对（容差 1e-9）。
* IR3. 缺参树：缺 t/R/角度/K 任一，校验 pending 且 build
  请求被扣下；实机端同样不许用默认值顶替。
* IR4. 非一致折弯树：两弯参数不同时 build 请求被扣下并注明
  bend_params_not_uniform；实机端不许自选一弯的值。
* IR5. 回滚：本包只新增 geometry_ir/ 文件；revert 即回滚，
  feature_tree/ 旧行为不受影响。

## 回滚方案

只新增 geometry_ir/ 目录与 #44 分支上的追加提交；不改
feature_tree/ 已有语义、不改已合并契约。回滚 = revert 本批
追加内容，IR 消费方回到 plan_id 引用方式。
