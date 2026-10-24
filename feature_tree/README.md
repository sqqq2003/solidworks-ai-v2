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
| sketch | points（≥3 个 [x, y]） | 闭合轮廓草图；mock 读回包络与 shoelace 面积 |
| extrude | depth_mm（>0）、direction（+z / -z / symmetric） | 拉伸；读回含依赖草图的面积（若有） |
| hole | center、diameter_mm（>0）、depth（{mode: through_all} 或 {mode: blind, depth_mm}） | 孔深必须显式选，不默认通孔 |
| bend | line{start,end}、thickness_mm（>0）、radius_mm（≥0）、angle_degrees（(0,180)）、k_factor（[0,1]） | 折弯；mock 算 BA = θ·(R+K·t)、BD = 2(R+t)·tan(θ/2) − BA |
| sheetmetal | outline_ref、bend_refs | 成组完成步骤：只在依赖的草图与折弯都执行完后记录汇总 |
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

## 与现有模块的关系（复用了什么、为什么新起目录）

* 模块 ③（dxf_extract/，Draft PR #35）：本模块直接消费它的
  plan.json（见上表），不另造一套接不上的输入。模块 ③ 的几何
  提取层（dxf_parser / geometry / relations）未被复制。
* #16（分支 feat/issue15-cad-features，交接 docs/issue15-handoff.md）：
  它的特征 IR（ql5050px.cad_features）在 dev 上不存在（仅分支
  上），且其执行要求主机端 create_editable_feature /
  verify_feature_tree 实现（不存在）。本模块是同概念的独立实现：
  有序可编辑特征 + 来源引用 + pending 状态 + 成环拒绝，与 #16
  交接中陈述的概念逐项对齐。待 #16 合并后，再做 #16 IR ↔
  feature-tree/1 的适配层（本批不做、不在本批静默分叉）。
* #20（统一原生建模，基线旧）：它的四类配方中，板件（带孔板
  件）与钣金（两折弯钣金）由本模块的示例与测试覆盖；L 支架可
  由 sketch + extrude + hole 组合表达（未单独给示例）；阶梯回
  转轴需要 revolve 类型——本模块暂不支持（未知类型拒绝），属
  未实现项，不与 #20 的文件重叠。
* #32 桥接 build 契约（Draft，未合并）：只作接口对齐参考——
  build 的每单参数、part_path 仅限 staging、幂等键、读回比对
  （容差 1e-6）等纪律与本模块一致；本批不依赖 #32，mock 优先。
* 本模块不复制 src/solidworks_generator.py（216KB，未逐行审
  计）的任何实现；只借用它的入口概念（生成入口 + 特征处理 +
  独占会话纪律）。

## 支持与不支持（诚实边界）

支持：上述 8 种节点类型（其中 fillet/chamfer 仅占位）、依赖排
序、成环/缺失依赖/重复 id/未知类型拒绝、fail-stop 执行、mock
产物与读回、CLI 端到端。

不支持（标 pending 或拒绝，不猜测）：revolve（回转）与 L 支架
以外的成型特征、真实 SolidWorks 执行（stub）、INSERT 块展开
（模块 ③ 同款边界）、整件展开长（需要各直边腿长，不在本模块
捏造）、材料 K 工艺表（缺依据，标待确认）。

已知待确认（本批未动、不属于本批范围）：dev 上
src/solidworks_generator.py 头部仍有一行
`DEFAULT_BEND_K_FACTOR = 0.44`（#29 删的是 BendAllowanceSpec
的默认值，这处生成器常量还在）。本模块不引用它、不依赖它；
统一它属于后续批次，不在本批顺手改。

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

## 回滚方案

本模块是纯新增目录（feature_tree/），不改任何现有文件。回滚
= 删除该目录 + 关闭对应 Draft PR；mock 产物只在调用方 out-dir
里，删 out-dir 即清干净。
