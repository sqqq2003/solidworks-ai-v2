# PR #69 — 有界建模与领域适配器统一交接

- PR：https://github.com/sqqq2003/solidworks-ai-v2/pull/69
- 代码 pin：`584c7ed1c5eb735a43290f74523fb20040825fd6`
- 代码 tree：`1a001736cc13302cea6ed69711166e4ba3edb192`
- 基线：#68 HEAD `5751ac7799fdd21be7b9f3ccf663d7ba3654572b`；保留 Windows/布局/目视门补丁。
- [完整源码包](gork-test-kit.zip)：567 个源码/受控合成夹具文件；1,359,797 bytes。
- ZIP SHA256：`36f87f0af5b78e1408739afdac9f600da7f0fb03dcc2feef0d4516ee49bfbef4`
- 内层 source.zip SHA256：`a3a55c477dbf876b2840a3bc91468b45474efce05538d3b71520929bb99b6def`

后续附件 HEAD 只添加交接材料，实机回传填写上述源码 pin。新目录、新虚拟环境；源码包不含 Windows/SolidWorks 运行时、客户 CAD、模板或凭据，不覆盖原安装、母图及旧包。不自动合并，不退出/杀 SolidWorks。

## 实际交付

1. 草图/挤出/切除/旋转白名单事务：先分析与审核 plan hash；原生步步校验特征类型、命名体、faces/bbox/volume；保存重开读回。
2. expected_revision 与保护特征库存：手改后拒绝脏写；中途手改保留现场隔离；失败整份检查点恢复并验证字节/库存。
3. 观测：相机还原、revision、BMP hash 和原子 JSON，只进入 reviewing。
4. 间隙：真实体有效性/距离测量、双 Copy2(False)、官方求交枚举 15901，分离/干涉/未知；失败和接触不明确不判零间隙通过。
5. 复用已有 owned STA/OS 锁/SQLite 回执，提取共享 CAD runner；同请求不重复插特征，冲突/未决先隔离对账。
6. 明确 modeling/sheet_metal adapter；钣金直接调用已有真实生成/展开，不重复框架。CLI、四个调用示例、保存半成品后的显式回滚故障工具及五项新 native 验收任务。

[完整接口、PowerShell 调用、范围和 Gork 五项检查](../../docs/modeling-domain-v9.md)。候选矩阵共 21 项，新项为 `modeling_named_bodies_and_features`、`modeling_half_build_rollback`、`modeling_revision_and_observation`、`modeling_body_clearance`、`modeling_request_replay_and_quarantine`。

## 核验与待办

`validation.json` / `targeted-tests.log`：157 项针对性检查通过，0 失败、错误、跳过；假 COM、实际临时文件恢复与 SQLite。不是全面回归、Windows/SolidWorks、桌面或人工目视结论。

`package-verification.json`：567 源码文件按 Git blob、pin、清单和 SHA 核对；实际导入新目录并检查候选完整性，未执行安装后的代码。GitHub 上传 21 个变更文件逐一与本地字节校验，并保留其余 709 个基线 blob。

只支持空白模板新建实体零件；不声称旧建模/钣金写入口已全部套用新事务。复杂弧线轮廓和新的建模目视签收 UI 待后续开发。无交集 Boolean 返回 NULL/错误时保守 unknown。本机语言/版本不同的平面和轴命名需先明确映射再审核计划，不猜轴。

Gork 统一验本源码 pin 的五项新检查及共享 runner 影响的出图/恢复回归。按 passed/degraded/failed/review_required 回传源 pin、环境、owned PID 证明、JSON/日志/BMP 相对路径与 SHA256。出图 D4 全六格、D2/D3/D5 目视、D6、旧 p248 未销项；所有 manufacturing_approved=false。外部 STEAL_NOTES.md 原文件仍未定位，不宣称已读其 §6。
