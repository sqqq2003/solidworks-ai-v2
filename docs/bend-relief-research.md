# 折弯交会处释放槽：业界做法调研（2026-10-25，WorkBuddy）

针对 p248（t=2.5mm, R=1mm, 90°，四折弯盒角，108/109 被拒）。
来源：SolidWorks 官方帮助/官方 API 示例 + 钣金加工 DFM 资料（见文末链接）。

## 三种正规做法

### 1. 折弯前手工切槽（平板上 cut 掉矩形/圆角槽）—— 传统做法

本项目现状方案（`convert_border_hole_to_notch` + `apply_rectangular_relief_expansion`），方向正确。

多来源汇总的尺寸规则：

| 参数 | 规则 | p248 代入（t=2.5, R=1） |
|---|---|---|
| 槽宽 W | ≥ t；常用 W ≥ t + R；精密厂公式 W ≥ t + 0.5mm；中文资料 K ≥ 2t | **3.5mm（t+R）～ 5mm（2t）** |
| 槽深 L | ≥ t + R（覆盖折弯变形区），且**必须超过折弯线交点 1～1.5mm** | **≥3.5mm + 越过交点 1~1.5mm** |
| 槽端圆角 | 末端加 R1.0～R1.5 防裂（应力集中点） | R1.0 |
| 槽型选择 | 薄板 ≤1.2mm 用圆形（应力均匀）；厚板 ≥3mm 用矩形 | 2.5mm：矩形或矩圆（obround） |

铝机箱实战规范（114my）：槽宽 ≥ 内R + 1.0mm；深度超过折弯交点 1~1.5mm；
"只开很小缺口、缺口没超过折弯交汇线，照样撕裂" —— 与本项目 relief_step 每 +1.0mm
逐级试的策略吻合，但**步进上限要够**：从基线到 t+R 可能不止 2 步。

### 2. Auto Relief（钣金特征级自动释放槽）—— **对盒角无效，勿走此路**

官方明确（Javelin/SW Help）：

- Auto Relief 在插入折弯时自动加，d = relief_ratio × t（ratio 0.05~2.0）
- Sketched Bend 特征可 Edit Feature → Custom Relief Type（Rect/Obround/Tear）
- **但 Auto Relief 不处理两条折弯交会的 corner treatment** —— 只管单条折弯端部

结论：调 Auto Relief 救不了 p248 的 108/109 交会角。

### 3. Corner Relief 特征（SW2018+ 官方正解，专门处理 2/3 折弯交会角）

- UI：插入 > 钣金 > 边角释放槽（Corner Relief），"收集所有边角" 自动收集
- 类型：Rectangular / Circular / Tear / Obround / Constant Width / Full Round / Suitcase
- 关键参数：Centered on bend lines（居中于折弯线交点）、Ratio to thickness
  （**让 SW 自己按板厚算槽长槽宽**，不用猜尺寸）、Tangent to bend、Add filleted corners

## 官方 API 调用序列（VB.NET 官方示例 → pywin32 可直接翻译）

官方示例 `Create_SM_Corner_Relief_Feature_Example_VBNET` 的建模流程是
**Base-Flange + 4 × InsertSheetMetal3dBend + Corner Relief** —— 与本项目 p248 生成管线完全同构：

```python
feat_mgr = model.FeatureManager
data = feat_mgr.CreateDefinition(
    swFeatureNameID_e.swFmCornerRelief)                    # 常量名在 swconst
model.Extension.SelectByID2(feature_name, "SOLIDBODY",
    0, 0, 0, False, 0, None, 0)                           # 选钣金实体
body = model.SelectionManager.GetSelectedObject6(1, -1)
data.Initialize(swCornerReliefBendType_e.swCornerReliefBendType_TwoBend)
data.SetBodyScope(body)
ok, corners = data.CollectAllCorners(
    swCornerReliefType_e.swCornerTearRelief)              # 返回所有角，默认 tear
for c in corners:
    c.AddFilletedCorners = True
    c.CornerFilletDiameter = 0.00025                      # m
    c.CenterOnBendLines = True
    c.TangentToBend = True
    c.ReliefType = swCornerReliefType_e.swCornerRectangularRelief
    c.RatioToThickness = True                             # 或显式 c.SlotLength = 0.009
feat = feat_mgr.CreateFeature(data)
```

修改已有 Corner Relief：`Feat.GetDefinition()` → `AccessSelections(model, None)` →
`GetCorners(-1)` 改属性 → `Feat.ModifyDefinition(data, model, None)`。

读取诊断：`data.GetCornerAtIndex(i, out)` → `SMCornerReliefData`
（ReliefType / SlotLength / SlotWidth / CenterOnBendLines / RatioToThickness /
GetFaces(face1, face2, face3)）。

本机为 SW2025（类型库主版本 33），该 API 完全可用。

## 对 p248 的关键辨析（重要）

**Corner Relief 特征救不了"折弯被拒绝"（BendRejected）。**

- Corner Relief 处理的是：折弯*成功之后*角部的干涉/起皱/外观 —— 它是在已折模型上加的切释放槽特征
- p248 的 108/109 是 `InsertSheetMetal3dBend` **特征创建被拒**，必须靠**折弯前手工切槽**
  （做法 1）把材料预先让开，折弯才可能成功
- 因此正确组合是：**折弯前切足尺寸的槽（按上表公式，W≥t+R=3.5mm，深越交点 1~1.5mm）
  → 折弯成功 → 可选：加 Corner Relief 特征做正式的边角处理（比手工槽更规整，且 SW 保证可展开）**

也就是说：本项目现有"手工槽 + 逐级扩大"的路线没错，可能的不足是
①基线槽尺寸低于 t+R；②步进 +1.0mm 上限不足；③槽深没越过折弯线交点。
下一轮实机建议先用**公式尺寸一步到位**（W=3.5~5mm、深越交点 1.5mm、端部 R1.0），
而不是从 +1.0mm 开始试。

## 参考

- SW Help 2027 API 示例: Create Sheet Metal Corner Relief Feature (VB.NET)
  help.solidworks.com/2027/english/api/sldworksapi/Create_SM_Corner_Relief_Feature_Example_VBNET.htm
- SW Help: Auto Reliefs (c_Auto_Reliefs.htm)；Corner Relief PropertyManager
  (HIDD_SHEET_METAL_CORNER_RELIEF.htm)
- SOLIDapps: How sheet metal corner reliefs are applied to the body（obround/Centered/Ratio 图解）
- Javelin-Tech: Auto vs Corner Relief（Auto Relief 不影响 corner treatment）
- okdor / mechnexus / essengoldparts：W≥t、L≥R+t 设计规则
- lsrpf：W ≥ T + 0.5mm、D ≥ R + T（精密公差公式）
- 114my（铝机箱转角撕裂）：槽宽 ≥ 内R+1.0mm、深超交点 1~1.5mm、槽端 R1.0~1.5
- 齐乐手板（盒体四角工艺槽）：K≥2t、L≥t+R+K/2
