# PR #70 — 函数参数建模完整调用链统一交接

- PR：https://github.com/sqqq2003/solidworks-ai-v2/pull/70
- **源码 pin：`6882a05e390327b1f44b0c18dd963c1a8747c0a0`**；代码 tree：`693715eb16489f978528acf31f7d72cb6dfb5af5`。
- 基于 #69 最新 `84bce400c18ad699b1ffe061521668a848fd7b4e`；保留旧源码/原生测试 pin，独立增量 PR，未合并。
- [完整源码测试包](gork-test-kit.zip)：599 个源码/受控合成夹具文件，1,450,245 bytes。
- ZIP SHA256：`d557cb5fb50dd28d2f32b21e8f75e6db9495e2b54d698ffc15dcbf94c29b28b5`。
- 内层 source.zip SHA256：`856b0528ec332afd299b49523e61e12b16164d2e6c10d0e32ab456311470b387`。

附件提交只添加交接材料，不代替源码 pin。新目录、新虚拟环境；包不含 Windows/SolidWorks 运行时、用户 CAD、模板或凭据，未执行安装后的代码。原程序、母图、旧包不覆盖，不自动合并。

## 实际代码

1. 受限数学表达式与 DAG：单位、范围、约束、循环/缺输入、整数孔数与角度计算；禁止任意Python/宏。复用已有依赖排序与参数工作台。
2. 函数参数物化到既有32步特征白名单，审核计划 SHA 和模板 SHA 后生成新可编辑零件，复用原生重建/命名体/保存重开/观测。
3. 已有独立零件副本读取线性尺寸、确认模型绑定、保护接口和允许范围；复用影响分析/具名审核/sw_api事务/typed尺寸编辑，按依赖序批量修改。
4. 复用检查点、revision、STA/OS锁/SQLite回执。m/mm和等价文档路径先规范化；保存失败或保护尺寸联动错误恢复整个基线。未决或手改不盲目重放。
5. 三页工作台与后台队列、规则编辑器、新建/已有零件两个执行入口、CLI、两份示例和保存参数批后的显式回滚故障工具。
6. 新流程 auto 无实例时打开，唯一空闲实例才复用；已有文档保留并拒绝。可显式 dedicated 或 idle_existing。统一收件器仅为四个新 parameter native 项核对严格空闲复用证据，旧项规则不变，记录通过不代替实机/工程验收。

[完整操作、接口、CLI和验收步骤](../../docs/function-modeling-v10.md)。启动 app.py → 参数化建模；依次计算、读取/绑定或选择空白模板、预览、具名确认、执行副本。成功读回仍为 reviewing，manufacturing_approved=false。

## 验证

`validation.json` 与 `targeted-tests.log`：160项针对性检查通过，0失败/错误/跳过；包含实际临时文件与SQLite、模拟COM和相关既有事务/验收合同。不是全面回归或SolidWorks实机。

`desktop-tests.log`：另5项实际Tk虚拟桌面检查通过，包含最小850×660窗口中关键按钮、数值变化失效、具名确认、后台队列、原入口。[界面截图](ui-preview.png)只展示合成参数，GUI源码blob与固定pin一致，不是CAD模型证据。任务自有Xvfb已停止。

`package-verification.json`：599文件按pin、Git blob和SHA核对，实际导入全新目录并复核候选；未执行其代码。26个变更blob核对，747个基线blob保持不变。初始代码提交及中间包未作为本最终pin验收，不能搬用旧统计。

## Gork 一次性接测

候选矩阵共26项；新增：`parametric_function_units_and_dependencies`（offline），以及 `parametric_generated_feature_part`、`parametric_existing_part_batch`、`parametric_review_and_request_replay`、`parametric_saved_batch_rollback`（native）。优先按上述文档完成新建块体、已有零件2–3个尺寸+保护项、会话/重放、真实Save3后回滚，再回归共享事务/收件器受影响部分；不要求重测所有项目后才能回传。

固定本源码pin，填写 Windows/Python/SolidWorks版本、原生PID/句柄、真实退出码、阶段JSON/日志/截图及SHA，按passed/degraded/failed/review_required分类。需要实机或人工目视的项不能用离线绿填通过；客户CAD/模板留本机。未决时保留模型副本、evidence和SQLite回执，沿现有安全对账，不重启/杀进程。

已有零件仅支持独立SLDPRT、单配置、最多64个正值driving线性尺寸；外部引用/装配、原生角度/计数、工程图/BOM联动不属于本批。角度与孔数可以计算，未绑定参数只计算。新建仍限既有特征白名单，非任意函数曲线/脚本。旧D4目视、D6、旧p248和QL整机映射问题不销项。
