# Issue50 API、调用与集中交测

候选基于dev aca899b2d7daf2d0b9a2edabda48a56a477b1711并明确复用PR45 758b1e533a11958784508736f3c05fc83abe0295。最终完整head见本PR/Issue50交接评论，不用分支名称代替证据pin。没有改原程序/客户CAD，没有启动本机SW，没有自动合并。

## 统一入口

```powershell
python work/engineering_intelligence.py batch examples/issue50-batch.json --out 'D:\工程\钣金导入\issue50-new'
python work/engineering_intelligence.py dimensions examples/issue50-dimensions.json
python work/engineering_intelligence.py tolerances examples/issue50-tolerances.json
```

其他命令：assembly、changes、review、transmission、weldments、costs、similarity、change_report、proposals、instruction。每项都有对应 examples/issue50-<命令>.json。API `engineering_intelligence.run_module(name, request)`；批量API `build_batch(request, destination=None)`。批量按P0→P1→P2执行，一个模块的输入错误会保留failed并继续其他模块。输出目录必须不存在；不覆写已有目录。传出request.json、engineering-result.json和HANDOFF.json，后者记录输入/结果及源码SHA256。示例是合成数据，不是OEM/供应商报价。请求可能包含本机路径，分享前复核。

退出码：passed=0、failed=1、degraded=2、review_required=3。这里passed仅表示**离线声明输入下计算/规则完成**，结果始终engineering_approved=false、native待验证。整个合成批的预期状态是review_required，因为未做原生配合/变更验收，中文指令还需绑定审核。

## 输入契约

| API/命令 | 主要输入与输出 |
|---|---|
| dimensions.solve_chain | dimensions唯一id、mm/value、datum、source、role、可选上下限；terms逐项dimension/direction±1；派生目标需显式solve_for指向唯一可调叶。输出before/after/changes和保护读回项；不支持多未知联立方程 |
| dimensions.tolerance_stack | 同基准的mm尺寸，tolerance含lower/upper/unit/source；有符号terms与可选required_interval_mm。无制造公差时worst_case=null；未自动采用任何公差等级 |
| assembly.diagnose_assembly | 既有components/mates/transmissions契约，加id；joints明确mm或deg、min/max/position/source。native_readback绑定review_digest({components,mates})并记录来源、SW scope与逐项检查，始终需要独立核对原生日志 |
| changes.track_changes | before/after文档节点，id/kind/source/revision/depends_on；输出改变、影响、删除、失效引用、再生成顺序及回退计划。节点含哈希字段时也纳入diff |
| review.review_design | values有value/unit/source；rules复用PR45格式，另含scope/confidence和suggestion；规则作用域/阈值不明待复核，不静默修复 |
| transmission.transmission | inputs每项value/unit/source：diameter mm、speed m/s、force N、ratio/efficiency/safety ratio。ratio=电机/滚筒转速；输出N*m/W/rpm。selection_requests显式category/requirements；复用来源/型号/修订/接口齐备的catalogue；电机追加功率、扭矩、转速检查，其他类别必须明确额定和接口要求 |
| weldments.plan_frame | profiles含材料、版本、来源、area mm^2/density kg/m^3/stock_length mm；members明确xyz端点、数量、每端余量mm、cut_type/source；kerf mm与connections。只支持直杆和声明接头，非方切待复核；每刀保守计锯缝；首适应递减不是最优套料 |
| costs.estimate_cost | currency/as_of；items有kind(material/process/standard_part)、quantity_unit、带来源数量与loss ratio、quote(value/currency/per_unit/source/date/valid_until)。损耗为毛料损失比例，gross=net/(1-loss)；缺价格仅输出known_subtotal，total=null；不自动换汇 |
| similarity.find_similar | parts含mm尺寸、features、material、interfaces、source及可选sha256；显式dimension_tolerance_mm。只提供候选/差异；文件哈希是调用者声明，必须实物核验；不替换 |
| changes.change_report | 复用changes输入，加parameter_differences/evidence(source/sha256)/validation_status；输出可审计摘要与回退，声明证据不当作文件哈希实检 |
| proposals.compare_proposals | gravity/chain/belt各方案metrics有value/unit/source；统一指标单位、weight、min/max偏好和来源；有缺项不评分，best_scheme始终null；不把加权分数当机械可行性 |
| proposals.instruction_request | text及可选binding_review；复用已有滚筒总长/保护语义，生成请求摘要，始终待审核且禁止原生写入 |

数值拒绝布尔/NaN/Inf，单位不自动猜测。无量纲也必须写ratio及来源。

## 衔接已有原生事务

`examples/issue50-native-review.json`提供**合成物理映射**示例，真实执行前必须换成真实审核映射、真实基线和原件/副本证据。

```python
from engineering_intelligence.native_review import prepare_native_review, execute_native_review
from design_review import record_approval
prepared = prepare_native_review(request)
# 将prepared['review']展示给工程师；由具名审核者独立提交当前摘要。
# approval = record_approval(prepared['review'], reviewer=actual_reviewer,
#                            review_sha256=actual_approved_digest)
# result = execute_native_review(request, approval, existing_owned_isolated_port, new_destination)
```

不提供自动批准CLI。port必须来自现有owned host/STA/PID/write gate，不能通过此API绕过。驱动叶尺寸进入事务；接口尺寸强制读回；overall等派生尺寸另列derived_readback_required。事务成功后仍须真实滚筒总长、保护几何/配合、重建、保存重开、原件哈希和正常退出验证，不能把write/readback当工程批准。焊接件只给native_feature_plan，不宣称已执行结构构件COM。

## 验证与回退

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_engineering_intelligence.py -v
python -m compileall -q src/engineering_intelligence work/engineering_intelligence.py
```

51项针对性离线检查全部通过（含3项既有计算/规则/BOM兼容检查）；12个单模块CLI及一次批处理调用完成。没有全库回归、GUI点击、Windows COM/真实样件验证。详情delivery/issue50/offline-checks.json。不得把继承PR45代码统称为本批全面测试通过。

Gork集中矩阵见delivery/issue50/windows-matrix.json；先继续#19/#24已有验收，不中断原生会话。每个测试固定实际SHA，原文件只读，独立新目录，记录SW/Python/模板版本、输入/输出哈希、完整traceback、保存重开和PID/退出码。缺真实样件、接口、公差或报价时review_required。返回一份证据PR回链Issue50/#46；不上传客户CAD。不强制结束未知SW进程。

回退：切回记录的dev基线或复用快照，在新目录重新生成报告；已有模型与失败现场保留。本批没有原件写操作，不需要对原程序做覆盖恢复。
