# 统一集成候选与运行说明

这是独立集成分支，不是dev/main已合并，也不是SolidWorks实机验收通过。来源固定在 delivery/integrated-v2/source-versions.json，涵盖PR20、28、43、44、45、47、48、52；完整候选SHA以本集成PR交接评论为准。原测试分支没有移动，原程序和客户CAD没有改写。

## 一个入口

```powershell
python work/project.py release examples/unified-project.json --out 'D:\工程\钣金导入\unified-new'
python work/project.py status
python app.py
```

桌面类型选unified，源文件选JSON、输出选一个尚不存在的目录，再加入QL/统一任务并运行队列。桌面走相同build_command/execute_job协议；没有从此入口执行原生CAD。GUI实际点击尚未测试。

该示例只含合成数据。预期输出review_required、退出码3；不能用已有文件/报告ZIP推定原生通过。输出目录必须是新目录；失败现场保留，不能删除恢复标记强行续跑。

处理链：
1. 调用已有QL integrated，得到只读快照分类、映射候选、改型决策、装配/传动/工程图/BOM任务。
2. 调用已有roller_variant，按两端轴头总长定义产生滚筒改型计划，交现有design_review做保护与影响审查。
3. link_roller_dimensions=true将滚筒真实声明基线转换成Issue50尺寸链，左轴头20、右轴头35、旧筒体945、旧总长1000的合成例得到新筒体745、总长800。不是另用Issue50的独立样例。若用户同时提供冲突尺寸链，整包失败。
4. 调用Issue50全部工程模块。link_machine_manufacturing=true将上游实际assembly_plan和图纸BOM传给平台制造输出；重复提供不同assembly_plan/components等时失败，不静默覆盖。
5. 输出统一release-result.json、分模块报告、文件及代码哈希HANDOFF.json和gork-unified.zip。原生审批、采购、制造批准始终不自动授予。

API：`unified_project.build_release(request, destination)`。schema_version=1；支持machine（原QL integrated请求）、roller（原滚筒请求）、roller_intentions（已有意图schema）、engineering（Issue50批请求）、platform（已有平台请求）以及两个显式link开关。它们保留原输入契约，不猜测OEM数据/公差/模板/钣金参数。源代码完整指纹、实际git HEAD（源码归档时明确unrecorded）和调用者声明版本分别记录，二者不混淆。

原有命令保留：work/project.py ql/review-parts/native-parts/review-production/native-production，work/run_reviewed_parts.py、work/roller_variant.py、work/design_platform.py、work/engineering_intelligence.py、work/audit_test_handoff.py。执行原生仍必须原有owned host/STA/PID/write gate、审核摘要和隔离副本。本包没有新增COM附着、强杀或自动批准命令。

PR44的geometry_ir/feature_tree是有边界的可编辑树/展开原型，保留原CLI `python -m geometry_ir.cli geometry_ir/examples/revolve_tree.json --out-dir <新目录>` 和独立测试；不能直接当作ql5050px特征IR或SolidWorks完整执行器，两者schema仍明确区分。

## 合并处理

- 基线dev aca899b2，先复用PR52（含PR45），再按共同基线整合PR20/28/47/48，随后三方整合PR43/44；没有从旧分支整目录覆盖新开发分支。
- 原生工程图：同时保留PR20的修改后模型receipt配置，以及dev的ReferencedConfiguration读回；任务配置冲突时拒绝。
- native_machine：保留一次typed应用绑定，避免重复注册或重新连接。
- owned launch：保留已有注册实例的启动前拒绝和详细诊断，同时保留PR47任务自有保活文档、借用STA初始化、真实退出核验及现场保留。
- PR47移植的新增特征文件以PR20对应文件作为内容来源祖先做三方合并，重复部分不再复制；仅末尾空行不同的文件保留明确来源版本。
- PR43兼容层与其余代码三方合并，相关sw_compat文件及owned_document_lifetime纳入计划/批处理/制造审核指纹，旧审核/续跑签名必须重建。
- S2旧模拟应用补齐模板/NewDocument，并断言自有保活文档存在，没有关闭生产保护或跳过断连检查。
- 历史results/windows及旧报告仅保留历史来源；不把PR43记录的失败或PR18旧折弯结果改成当前通过。生成的历史results/cloud/latest.json不作为集成结论。

逐文件记录：delivery/integrated-v2/merge-decisions.json；新原生检查清单：delivery/integrated-v2/windows-matrix.json。

## 复现离线验证

```powershell
python -m pip install -r requirements-cloud.txt
python work/run_integrated_tests.py --out '<新的离线结果目录>'
python -m compileall -q src work app.py feature_tree geometry_ir
```

统一runner覆盖原库回归、原36项特征合约、feature_tree与geometry_ir四组。真实统计见delivery/integrated-v2/offline-checks.json；跳过项明确为本地缺失DWG样件、LibreDWG转换器、原始基线源码哈希夹具。跨进程写锁检查另记。兼容层集成新增尺寸链/制造关联、输入不变/输出防覆盖、桌面队列调用同一CLI及源码指纹检查。

## Gork集中验收与回退

优先完成现有#19/#24任务，不中断正在运行的SW；下一轮可领取本候选一个完整SHA，新目录/独立环境重建审核和计划，不叠加旧ZIP。先原生会话/三次独立正常退出，再S1/S2/展开，再真实滚筒800、四配方、p248黄金回归、整机/图纸/BOM及平台/Issue50。PR43改变部分轮廓/车件及COM适配，p248四折弯、尺寸和退出必须重新验，离线通过不是几何算法等价证据。

返回一个证据PR，记录候选SHA、输入/源码/产物哈希、SW/Python/模板版本、原件不变、阶段日志/完整traceback、保存重开读回和真实退出码。未知归属或进程仍存活时停止该原生队列，不kill，不清恢复标记。缺OEM数据、制造公差、目录报价等一律review_required。

回退代码：切回source-versions记录的dev或具体源PR版本，在新目录生成输出。保留原件、失败现场及历史证据。不reset/覆盖用户原程序，不强推，不自动合并本PR。
