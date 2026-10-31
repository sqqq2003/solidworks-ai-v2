# DXF 几何 / 尺寸关系提取及特征计划（Issue #25 扩展模块 ③）

离线模块，纯 Python 标准库，不依赖 SolidWorks、不依赖 ezdxf。
输入一个 ASCII DXF 文件，输出两份 JSON：几何提取与特征计划。

## 调用

```bash
python -m dxf_extract.cli dxf_extract/examples/flat_pattern.dxf \
    --out-dir out
python -m dxf_extract.cli dxf_extract/examples/flat_pattern.dxf \
    --out-dir out --job-params job.json
python -m dxf_extract.cli input.dxf --out-dir out --assume-units mm
```

退出码：0 = 解析成功（即使有 flagged 实体或 pending 特征，两者都会
报告出来，不藏起来）；2 = 输入错误（文件缺失、二进制或畸形 DXF、
job-params 文件坏、--assume-units 非法）。输入文件永不被修改。

`job.json` 示例（四个键缺一不可，缺了就是 pending，绝无默认值）：

```json
{"thickness_mm": 2.5, "radius_mm": 1.0, "angle_degrees": 90.0, "k_factor": 0.36}
```

注意：上面这组数只是**调用示例**，不是默认值。t、R、K、角度一律
按每单输入参数处理；t=2.5 / R=1 / K=0.36 只是本厂一次实测用例。

## 输出格式

### geometry.json

```json
{
  "format": "dxf-extract/1",
  "source_file": "…",
  "units": "mm",
  "units_factor_mm": 1.0,
  "bounds": [min_x, min_y, max_x, max_y],
  "flags": ["…"],
  "entities": [
    {"id": "e001", "type": "LINE", "layer": "OUTLINE",
     "status": "ok", "flags": [],
     "geometry": {"start": [0, 0], "end": [100, 0], "length": 100.0}},
    {"id": "e005", "type": "CIRCLE", "layer": "HOLES",
     "status": "ok", "flags": [],
     "geometry": {"center": [25, 30], "radius": 5.0}}
  ]
}
```

### plan.json

```json
{
  "plan_version": "dxf-extract/1",
  "source_file": "…",
  "units": "mm",
  "features": [
    {"id": "f-001", "type": "contour", "params": {"points": [[…]]},
     "sources": ["e001"], "confidence": "high",
     "status": "confirmed", "pending_reasons": []},
    {"id": "f-002", "type": "hole",
     "params": {"center": [25, 30], "diameter_mm": 10.0},
     "sources": ["e005"], "confidence": "high",
     "status": "confirmed", "pending_reasons": []},
    {"id": "f-003", "type": "bend_line_candidate",
     "params": {"start": [70, 0], "end": [70, 100], "length_mm": 100.0,
                "layer_hint": true},
     "sources": ["e002"], "confidence": "high",
     "status": "pending_confirmation",
     "pending_reasons": ["job_params_missing:thickness_mm,radius_mm,angle_degrees,k_factor"]}
  ],
  "relations": [{"kind": "parallel", "entities": ["e001", "e003"], "distance_mm": 60.0}],
  "pending": ["…"],
  "stats": {"entity_count": 7, "flagged_entity_count": 0,
            "feature_count": 4, "relation_count": 6}
}
```

特征类型：`contour`（闭合轮廓）、`hole`（轮廓内的圆孔）、
`bend_line_candidate`（开放直线段，沿用 `cad_analyzer` 的手动折弯线
候选规则：开放 + 直线；BEND/FOLD 层名只提高置信度，不单独作为依据）、
`flat_pattern`（轮廓 + 折弯线候选）、`dimension_check`（直径/半径标注
与圆的对照）。

## 与现有模块的关系（复用了什么、为什么新起目录）

* `src/cad_analyzer.py`（dev 已有，ezdxf 解析）：已实现 DXF 实体 →
  Primitive / 剖面 / 折弯线 / 文字的管线。本模块**不替换它**：本模块
  是依赖为零的独立提取层，实体模型与它的词汇对齐（点 / 层 /
  类型 / 圆心半径），输出的 JSON 可与它的结果逐项对照（见下验收）。
* #16 交接（`docs/issue15-handoff.md`）明确列出的未完成项是
  "dimension relation inference, block expansion"：本模块**补上前一半**
  （标注测量、平行/垂直/相切/共心/等半径、标注与圆的对照），
  **块展开仍未做**：INSERT 实体只记录块名并标 pending，不展开、
  不猜测块内几何。
* #16 的特征 IR（`ql5050px.cad_features`）在 dev 上不存在（只在
  #16 分支上），所以本模块的特征计划是独立实现的同概念版本：
  有序特征 + 来源实体引用 + pending 状态；待 #16 合并后再做适配层，
  不在本批静默分叉。
* 钣金口径沿用 `csharp-bridge/SHEET_METAL_RULES.md`：BA =
  θ·(R+K·t)，BD = 2(R+t)·tan(θ/2) − BA；单位沿用
  `csharp-bridge/CONTRACT.md`：显式 mm / 度。
* TEXT/MTEXT 只记录为备注，**永不从文字里推导参数**（写着
  "t=2.5" 的文字不是板厚测量）。

## 支持与不支持（诚实边界）

支持：LINE、CIRCLE、ARC、LWPOLYLINE（含 bulge 圆弧段）、POLYLINE、
DIMENSION（旋转 0、对齐 1、直径 3、半径 4 这四个子集）、TEXT/MTEXT
（仅记录）。DIMENSION 的子集说明：旋转标注需要 13/14 延长线原点与
50 角度；直径/半径标注需要 15 圆心与 10 圆上点与已解析的圆匹配上，
否则标 pending；角度标注（2、5）与坐标标注（6）不支持，标 pending。

不支持（标 flagged，不猜测）：二进制 DXF、SPLINE（不拟合）、
ELLIPSE（不近似成圆弧）、INSERT 块展开、缺端点的 LINE、半径 ≤ 0
的圆/弧、歧义的闭环（分支顶点）、单位未知的绝对尺寸断言。

## 未实现 / 待确认

* 块（INSERT）展开；样条/椭圆精确几何；角度/坐标标注；三维
  DXF（Z 坐标读取后忽略，只做 XY 平面提取，Z 非零时不报错但
  不用于计算——调用方须知）。
* 展开长度：只算每弯的 BA/BD（且仅当 job 参数齐全时），不算
  整件展开长——那需要各直边腿长，须由轮廓几何另行量取，不
  在本模块捏造。
* 全部 Windows / SolidWorks 行为均为 pending_windows_validation。

## 给 Gork 的 Windows / 实机验收增补

1. **提取对照**：取同一张 DXF，先用本模块出 geometry.json，再用
   SolidWorks 打开同一文件读实体清单；逐项对照实体数量、类型、
   圆心/半径、轮廓点——差值超过 1e-3 mm 即判不一致。
2. **孔对照**：plan.json 里的每个 hole，与 SolidWorks 重建后
   的孔位置/直径对照；圆心偏差超过 1e-3 mm 即判不一致。
3. **折弯线对照**：plan.json 里的 bend_line_candidate，与
   SolidWorks 展开图上的折弯线位置对照；多一条、少一条都算
   不一致，须查是层名规则还是直线判定规则的问题。
4. **标注对照**：plan.json 里的 dimension_check 与 SolidWorks
   标注读数对照；text_override_mismatch_pending 的项须人工定。
5. **回滚**：本模块只读输入、只写 --out-dir，不动任何 CAD
   原件与工作副本；验收失败时删除 out-dir 即可回滚，无需动
   仓库与 SolidWorks 状态。
