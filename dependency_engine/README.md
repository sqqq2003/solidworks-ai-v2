# 整机参数依赖、装配关系、冲突预检辅助引擎（Issue #25 扩展模块 ⑤）

离线模块，纯 Python 标准库，不依赖 SolidWorks。输入一台整机的参数
与装配关系，做**静态预检**：参数能不能算出来、装配关系有没有冲突、
改一个参数会波及哪里。只出报告，不写任何 CAD 文件，不碰任何工作
副本。真实 SolidWorks 行为均为 pending_windows_validation。

## 调用

```bash
# 预检一台整机（合成示例：封箱机机架宽度联动）
python -m dependency_engine.cli dependency_engine/examples/frame_linkage_ok.json \
    --out-dir out
# 只看改动某个参数前的确认链
python -m dependency_engine.cli dependency_engine/examples/frame_linkage_ok.json \
    --out-dir out --change machine_width
```

退出码（与模块 ③④ 同款约定）：
* 0 = 预检通过（无 pending、无 error；warning 不影响退出码，但会列出）；
* 1 = 报告已写出，但机器处于 pending 或 conflict；
* 2 = 输入错误（文件缺失、JSON 坏、格式不对、重名参数、依赖成环、
  同一参数既给值又给公式、未知公式 op、单位未显式声明）。

输入文件永不被修改；输出只写进 `--out-dir`（precheck.json）。

## 输入格式（dependency-engine/1）

```json
{
  "format": "dependency-engine/1",
  "name": "…",
  "units": "mm",
  "parameters": [
    {"name": "machine_width", "unit": "mm", "value": 1000, "subsystem": "frame"},
    {"name": "frame_width", "unit": "mm",
     "formula": {"op": "subtract", "args": ["machine_width", "side_allowance", "side_allowance"]}},
    {"name": "cover_width", "unit": "mm"}
  ],
  "parts": [
    {"id": "beam_front", "label": "前横梁",
     "uses_parameters": ["beam_length"], "feature_refs": ["f-001"]}
  ],
  "mates": [
    {"id": "m1", "kind": "coincident", "part_a": "beam_front", "part_b": "column_left"},
    {"id": "m5", "kind": "distance", "part_a": "guide_left", "part_b": "guide_right",
     "axis": "x", "value_param": "guide_spacing"}
  ]
}
```

参数规则（缺了就 pending，绝无默认值）：
* `unit` 必须显式声明（mm / deg / count / unitless），不声明即输入错误。
* 叶参数给 `value`；派生参数给 `formula`；既无值又无公式的
  参数是 `pending_mapping`（沿用 a01_parametric 的叫法），不猜数。
* 公式 op：`copy`（1 个 arg）、`add`、`subtract`、`scale`（1 个
  arg + `factor`)。`min` / `max` 是可选的显式范围，越界时该参数
  pending（out_of_range），**不截断、不猜值**。
* 同一参数既给值又给公式是输入错误（歧义输入直接拒绝，不猜）。
* t、R、K、角度、整机尺寸一律按每单输入参数处理；t=2.5 / R=1 /
  K=0.36 只是本厂一次实测用例，不是默认值。钣金 BA/BD 不在本模块
  算（那是模块 ②④ 的公式链，这里不重复造）；K 的单位是 unitless，
  范围如需限制由调用方在 `min` / `max` 里显式给。

装配约束（mate）种类：
* `coincident`：两零件位置重合（约束 x、y、z 三轴）；
* `distance`：沿 `axis` 的间距，值来自 `value_mm` 或 `value_param`
  （参数未确认时该 mate pending）；
* `align`：沿 `axis` 的中心对齐；
* `parallel` / `perpendicular`：只约束方向，不参与位置冲突检查。

## 预检规则（静态检查，不解算自由度）

* 参数解析：Kahn 拓扑排序（输入顺序稳定，与模块 ④ 同款）；
  依赖成环、重名参数直接判输入错误，**不猜顺序**。
* 参数缺失、公式引用不存在、上游未确认、越界 → 该参数及其下游
  一律 pending，并在 `pending_items` 里列出缺失项。
* 装配冲突按（零件对，轴）检查——同一对零件在同一轴上：
  * 两个位置约束值不同 → error（contradiction）；
  * 两个位置约束值相同 → warning（redundant_constraint）；
  * 自身 mate（part_a == part_b）→ error（self_mate）；
  * 引用不存在的零件、间距参数未确认 → 该 mate pending。
  * 一个零件完全没有任何位置 mate → warning（under_constrained）。
* 影响范围：改动任一参数时，`impact` 列出所有下游参数（拓扑序）、
  用到它们的零件、引用它们的 mate、以及这些零件带的
  `feature_refs`（模块 ③ 的特征 id / 模块 ④ 的节点 id，仅列出、
  不解析）。`confirm_chains` 给出每条"改动 X 前请先确认 Y"链：
  confirm_first 是 X 的上游里仍 pending 的参数。
* 报告 `status`：有 error → conflict；否则有 pending → pending；
  否则 ok（warning 不改变 status，但全部列出）。

## 示例（全部是合成数，不是客户尺寸、不是默认值）

| 文件 | 讲什么 | 预期结果 |
|---|---|---|
| examples/frame_linkage_ok.json | 改整机宽度时横梁 / 辊筒 / 导向杆间距 / 防护罩的联动（改宽 7 步清单里横梁、辊筒、横轴、导向杆间距、防护罩的联动关系） | ok：frame_width 940、roller_length 920、guide_spacing 880、cover_width 970 |
| examples/frame_linkage_conflict.json | 同一对导向杆上参数间距 880 与字面间距 850 打架；辊筒偏移值重复给两次 | conflict：1 个 contradiction error + 1 个 redundant warning |
| examples/frame_linkage_pending.json | side_allowance 与 k_factor 未确认；一个 mate 引用不存在的零件；一个零件未定位 | pending：下游参数 pending、mate pending、under_constrained warning |

## 与现有模块的关系（复用了什么、为什么新起目录）

* `src/a01_parametric/graph.py`（dev）：复用其词汇——depends_on
  边、copy / pending_mapping 种类、frame / conveyor / drive / mount
  子系统划分、减法链；本模块的公式层是它的通用化（任意参数名，
  不只 A01 的固定节点）。
* `src/ql5050px/parameters.py`（dev）：复用其纪律——OEM 缺失 stays
  null、只有 confirmed 输入才解析、派生值来自显式设计关系；
  本模块的 pending_mapping 与它同义。QL-5050PX 真实 OEM 尺寸仍有
  10–12 项 pending_mapping，示例一律用合成参数，绝不填数。
* `src/a01_parametric/constraints.py`（dev）：单位显式、mm 值为正、
  范围校验、pending_mapping 不得带伪造值——本模块照搬前三条，
  范围违规改为 pending（预检的职责是报告缺口，不是拒绝整单）。
* 模块 ③（dxf_extract/，Draft PR #35）：输入输出口径对齐——版本
  化格式串、单位显式 mm、confirmed / pending_confirmation 状态、
  退出码 0/1/2、输入不修改、只写 out-dir；零件的 `feature_refs`
  可挂模块 ③ 的特征 id，本模块不解析 plan.json。
* 模块 ④（feature_tree/，Draft PR #36）：依赖图语义一致——Kahn
  排序、成环拒绝、缺参数 pending、不猜顺序；本模块不复制它的
  执行器与 mock 后端，只在影响范围里引用特征 id。
* #16（分支 feat/issue15-cad-features）：它的特征 IR 与装配概念只
  在分支上，dev 上不存在；本模块的零件 / mate 模型是独立实现，
  待 #16 合并后再做适配，不在本批静默分叉。
* #20（统一原生建模，基线旧）：它的四类配方与装配概念是本模块
  的下游消费者（预检通过后才值得上机执行），本模块不依赖它。
* #32 桥接 build/reopen 契约（Draft，未合并）：本模块不依赖桥接；
  预检报告可作为 build 前的门禁输入（status 非 ok 时调用方应先
  处理 pending/conflict），但本批不接线、不改 run_plan。
* 本模块不复制 `src/solidworks_generator.py` 的任何实现；只借用
  它的纪律（生成入口 + 独占会话），且**不引用**该文件头部残留的
  `DEFAULT_BEND_K_FACTOR = 0.44`（#29 删的是 BendAllowanceSpec 的
  默认值，这处生成器常量还在；统一它属于后续批次，本批不碰它，
  测试里有断言保证本模块不引用它）。

## 支持与不支持（诚实边界）

支持：上述参数公式与装配约束、拓扑排序、成环/重名拒绝、缺失与
越界 pending、成对矛盾/冗余/未定位检查、影响范围与确认链、CLI
端到端。

不支持（标 pending 或拒绝，不猜测）：完整自由度求解（本模块只做
成对静态检查，不证明整机完全约束）；几何干涉与运动仿真；三维
装配位置解算；材料 K 工艺表（缺依据，标待确认）；真实
SolidWorks 执行（本模块根本不写 CAD，谈不上执行）。

## 给 Gork 的 Windows / 实机验收增补

1. **门禁对照**：取一台已知的整机参数表，先用本模块出预检报告，
   再与 SolidWorks 装配体的实际配合状态逐项对照——本模块报
   contradiction 的对子在实机上也应是过约束或干涉，报
   under_constrained 的零件在实机上也应是可拖动的。
2. **改宽联动对照**：按 ok 示例改整机宽度，实机上横梁 / 辊筒 /
   导向杆间距 / 防护罩的联动清单应与报告的 impact 一致，少一
   项、多一项都算不一致。
3. **pending 门禁**：status 非 ok 的报告不得直接用于 build；调用
   方应先补齐 pending 项或处理 conflict，实机端同样拒绝执行。
4. **回滚**：本模块是纯静态检查，不写 CAD、不改仓库现有文件；
   回滚 = 删除 dependency_engine/ 目录 + 关闭对应 Draft PR，
   out-dir 一删即清干净。

## 回滚方案

本模块是纯新增目录（dependency_engine/），不改任何现有文件。
回滚 = 删除该目录 + 关闭对应 Draft PR；预检产物只在调用方
out-dir 里，删 out-dir 即清干净。
