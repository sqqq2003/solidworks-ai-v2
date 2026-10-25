# 原生可编辑特征树执行接口与 mock（Issue #25 扩展模块 ④）

离线模块，纯 Python 标准库，不依赖 SolidWorks。输入一棵特征树
（或模块 ③ 的特征计划），按依赖顺序执行，输出执行记录与 mock
产物。真实 SolidWorks 后端目前只有 stub（见 real_backend.py），一切
实机行为均为 pending_windows_validation。

## 调用

```bash
# 直接执行一棵特征树
python -m feature_tree.cli feature_tree/examples/plate_holes_tree.json \
    --out-dir out
# 执行 L 支架示例树（sketch + extrude + hole 组合）
python -m feature_tree.cli feature_tree/examples/l_bracket_tree.json \
    --out-dir out
# 整件展开长（只读树 JSON，写 out/unfold.json）
python -m feature_tree.unfold \
    feature_tree/examples/sheetmetal_unfold_tree.json --out-dir out
# 执行模块 ③ 的计划（需每单参数；缺了就 pending，绝无默认值）
python -m feature_tree.cli feature_tree/examples/plan_sample.json \
    --out-dir out --job-params feature_tree/examples/job_sample.json
# 顺带写出转换后的特征树
python -m feature_tree.cli feature_tree/examples/plan_sample.json \
    --out-dir out --job-params feature_tree/examples/job_sample.json \
    --tree-out out/tree.json
```

退出码（与模块 ③ 同款约定）：
* 0 = 执行完成（status ok）；
* 1 = 执行中途停下（某节点 pending 或失败），记录仍写出，后续
  节点无步骤、无产物条目；
* 2 = 输入错误（文件缺失、JSON 坏、版本不对，或树校验错误：
  重复 id、未知类型、缺失依赖、依赖成环）。

输入文件永不被修改；输出只写进 `--out-dir`（execution.json 与
mock_part.json）。

## 特征树 IR（feature-tree/1）

```json
{
  "tree_version": "feature-tree/1",
  "name": "…",
  "units": "mm",
  "features": [
    {"id": "s1", "type": "sketch",
     "params": {"points": [[0, 0], [100, 0], [100, 60], [0, 60]]},
     "depends_on": [], "sources": [],
     "status": "confirmed", "pending_reasons": []}
  ]
}
```

节点类型与参数（缺必填项即 pending_confirmation，不猜数）：

| 类型 | 必填参数 | 说明 |
|---|---|---|
| sketch | points（≥3 个 [x, y]）、closed（可选，默认 true） | 闭合轮廓草图；mock 读回包络与 shoelace 面积；closed=false 时 revolve 拒绝 |
| extrude | depth_mm（>0）、direction（+z / -z / symmetric） | 拉伸；读回含依赖草图的面积（若有） |
| hole | center、diameter_mm（>0）、depth（{mode: through_all} 或 {mode: blind, depth_mm}） | 孔深必须显式选，不默认通孔 |
| bend | line{start,end}、thickness_mm（>0）、radius_mm（≥0）、angle_degrees（(0,180)）、k_factor（[0,1]） | 折弯；mock 算 BA = θ·(R+K·t)、BD = 2(R+t)·tan(θ/2) − BA |
| revolve | profile_sketch（已执行草图 id）、axis{origin, direction}、angle_degrees（(0,360]） | 回转；见下节 revolve 规范；mock 用 Pappus 定理读回体积 |
| sheetmetal | outline_ref、bend_refs、straight_lengths_mm（展开用，见下节） | 成组完成步骤：只在依赖的草图与折弯都执行完后记录汇总 |
| check | value_mm（另有 dimension、circle 引用） | 尺寸核对记录步骤：只记录模块 ③ 的计划级核对结果，mock 不重测 |
| fillet、chamfer | — | 占位类型：IR 接受，mock 执行时 pending（unsupported_in_mock），不猜参数 |

执行语义：依赖顺序是唯一顺序（Kahn 算法，输入顺序稳定）。
重复 id、未知类型、缺失依赖、依赖成环都在执行前拒绝（输入错
误）。执行是 fail-stop：第一个无法执行的节点即停，后续节点不
产生任何步骤与产物。

## 模块 ③ 计划的转换（plan_convert.py）

| 计划特征（dxf-extract/1） | 转换后节点 | 依赖 |
|---|---|---|
| contour | sketch | — |
| hole | hole（depth 来自调用方 job 参数的 hole_depth_spec） | sketch |
| bend_line_candidate | bend（t/R/角度/K 来自调用方 job 参数） | sketch |
| flat_pattern | sheetmetal（outline_ref、bend_refs） | sketch + 各 bend |
| dimension_check | check | 由其 circle 实体对应的 hole（如有） |

计划期带有的 `job_params_missing:*` 理由在转换时会被清除后按当
前 job 参数重算：调用方补上参数后，原来 pending 的折弯/成组节
点恢复 confirmed；仍缺的继续 pending。计划中未知的特征类型转
换时拒绝，绝不静默丢弃（丢特征等于改零件）。

job 参数示例（全部是示例输入，不是默认值）：

```json
{"thickness_mm": 2.0, "radius_mm": 1.5, "angle_degrees": 90.0,
 "k_factor": 0.38, "hole_depth_spec": {"mode": "through_all"}}
```

t、R、K、角度一律按每单输入参数处理；t=2.5 / R=1 / K=0.36 只是
本厂一次实测用例，不是默认值。

## 补齐批新增：revolve 规范与整件展开长（#36 之后补齐）

### revolve（回转）

参数（全部必填，无默认值）：
* `profile_sketch`：已执行草图节点的 id，且必须接在
  depends_on 里（否则执行顺序上轮廓还没跑出来，revolve 以
  profile_sketch_not_executed pending 停下，绝不先读后补）。
* `axis`：`{origin: [x, y], direction: [dx, dy]}`，草图平面内
  的回转轴线；方向必须是非零向量，否则为范围错误（failed）。
* `angle_degrees`：显式角度，(0, 360]；360 为整圈；缺失为
  pending，超出范围为 failed（与折弯角 (0, 180) 的区间不同，
  不要混用）。

硬校验（mock 执行时执行，绝不猜修法）：
* 轮廓未闭合：草图声明 closed=false 时，revolve 以
  revolve_profile_not_closed pending 停下。本 IR 的草图默认闭
  合（≥3 点即按闭合多边形处理），所以"不闭合"只能由显式声
  明表达，不由执行器猜。
* 退化轮廓：shoelace 面积为 0（共线点等）时以
  revolve_profile_degenerate pending 停下——零面积轮廓回转不
  出实体。
* 穿越回转轴：轮廓顶点严格落在轴线两侧时以
  revolve_profile_crosses_axis pending 停下；恰好落在轴线上的
  点允许（轮廓边贴轴是正常情况）。
* 读回：mock 用 Pappus 定理算体积
  V = 面积 × 弧度角 × 形心到轴距离，标 mock_readback。

revolve 树由树 JSON 直接编写，不从模块 ③ 计划转换：DXF 计
划里没有回转候选类型，发明一个转换映射等于猜几何。

### 整件展开长（unfold.py，BA 法）

公式（与 csharp-bridge/SHEET_METAL_RULES.md 同款）：

```
展开长 = 直边和 + Σ 每处折弯的 BA
BA = θ·(R + K·t)，每处折弯按自己的 t/R/角度/K 现算
```

直边长（量到折弯切点）不能从成型轮廓草图推导——成型外框
决定不了展开直边，猜了就是编造几何。所以直边来源只能是显
式输入，优先级：调用方 `compute_unfold(tree,
straight_lengths_mm=[...])` 参数 > sheetmetal 节点的
`straight_lengths_mm` 参数；两处都没有时结果 pending 并列出
缺失项，绝不以默认值顶替。

pending 纪律：任一折弯缺 t/R/角度/K 或超范围时，该折弯不产
BA、整件结果 pending 且 unfold_length_mm 为 None，已算出的
折弯 BA 仍列在报告里（不静默跳过未算折弯）；非钣金特征（孔、
拉伸、回转、核对、倒角/圆角占位）列在 excluded 里，不进长度；
轮廓草图列为 outline_reference，不进长度；一棵树有多个
sheetmetal 成组节点时报告 pending（组间关系未建模，不跨组
求和）。

CLI（退出码同款约定：0 ok、1 pending（报告仍写出）、2 输
入错误；输入文件永不修改，只写 out-dir/unfold.json）：

```bash
python -m feature_tree.unfold <tree.json> --out-dir out
python -m feature_tree.unfold <tree.json> --out-dir out \
    --straight-lengths 30,40,30
```

## 与现有模块的关系（复用了什么、为什么新起目录）

* 模块 ③（dxf_extract/，已合并 PR #35）：本模块直接消费它的
  plan.json（见上表），不另造一套接不上的输入。模块 ③ 的几何
  提取层（dxf_parser / geometry / relations）未被复制。
* #16（分支 feat/issue15-cad-features，交接 docs/issue15-handoff.md）：
  它的特征 IR（ql5050px.cad_features）在 dev 上不存在（仅分支
  上），且其执行要求主机端 create_editable_feature /
  verify_feature_tree 实现（不存在）。本模块是同概念的独立实现：
  有序可编辑特征 + 来源引用 + pending 状态 + 成环拒绝，与 #16
  交接中陈述的概念逐项对齐。待 #16 合并后，再做 #16 IR ↔
  feature-tree/1 的适配层（本批不做、不在本批静默分叉）。
* #20（统一原生建模，基线旧）：它的四类配方至此全部由本模
  块的示例与测试覆盖——带孔板件（plate_holes_tree.json）、L
  支架（l_bracket_tree.json，补齐批新增）、阶梯回转轴（revolve
  类型，补齐批新增；示例树由调用方按 revolve 规范编写）、两折
  弯钣金（sheetmetal_two_bends_tree.json，另有带展开数据的
  sheetmetal_unfold_tree.json）。本模块与 #20 的文件不重叠。
* #32 桥接 build 契约（已合并）：只作接口对齐参考——build
  的每单参数、part_path 仅限 staging、幂等键、读回比对（容差
  1e-6）等纪律与本模块一致；本批不依赖桥接执行，mock 优先。
* 本模块不复制 src/solidworks_generator.py（未逐行审计）的任
  何实现；只借用它的入口概念（生成入口 + 特征处理 + 独占会
  话纪律）。该生成器头部残留的 `DEFAULT_BEND_K_FACTOR =
  0.44` 已由后续清理批 PR #40 删除（本模块从未引用它）。

## 支持与不支持（诚实边界）

支持：上述 9 种节点类型（其中 fillet/chamfer 仅占位）、依赖排
序、成环/缺失依赖/重复 id/未知类型拒绝、fail-stop 执行、mock
产物与读回、CLI 端到端、revolve 回转、L 支架示例、整件展开长
（BA 法，直边须显式输入）。

不支持（标 pending 或拒绝，不猜测）：revolve 以外的成型特征
（如 sweep）、真实 SolidWorks 执行（stub）、INSERT 块展开（模
块 ③ 同款边界）、多 sheetmetal 成组节点的跨组展开（未建模，
报告 pending）、材料 K 工艺表（缺依据，标待确认）。

## 给 Gork 的 Windows / 实机验收增补

1. **执行对照**：同一棵特征树，先用 mock 出执行记录，再用实
   机后端执行；逐项对照步骤顺序、特征类型、孔位/直径、折弯
   BA/BD——差值超过 1e-6 即判不一致。
2. **读回对照**：实机 reopen 后读回特征树、钣金定义、
   CustomBendAllowance，与计划参数比对（容差 1e-6），不一致
   即失败（与 #32 reopen 契约同款纪律）。
3. **成环/缺依赖拒绝**：在实机端同样拒绝执行，不许实机端
   "猜顺序"把环跑通。
4. **失败隔离**：执行中途失败时，后续特征无产物、无文档写
   入；收尾仍按 #23/#31 纪律（失败记证据 + crash 包、产物不
   反发布、退出码原样记录）。
5. **回滚**：mock 产物只写 out-dir，删 out-dir 即回滚；实机
   端只写 run 的 staging 工作副本路径，绝不写客户原件。
6. **revolve 对照**：同一棵回转树，mock 体积（Pappus）与实
   机回转体积比对（容差 1e-6）；轴穿越/未闭合/退化轮廓在实机
   端同样拒绝，不许实机端"修一下跑通"。
7. **展开长对照**：同一棵钣金树，mock 展开长（BA 法）与实机
   展开读回比对（容差 1e-6）；缺参数时实机端同样 pending，不
   许用默认值顶替。
8. **向后兼容对照**：补齐前已有的示例树（带孔板件、两折弯钣
   金）在补齐后的执行记录与旧记录逐项一致（步骤、顺序、读
   回、产物键），新增的 revolve/展开能力不得改变旧树行为。

## 回滚方案

本批只改 feature_tree/ 内文件（tree.py、mock_backend.py、
__init__.py、plan_convert.py 的注释、README.md、tests/ 与
examples/ 的新增与一处探针修改），不改任何其他目录。回滚 =
revert 本 PR；旧类型树的执行行为不受影响，mock 产物只在调用
方 out-dir 里，删 out-dir 即清干净。
