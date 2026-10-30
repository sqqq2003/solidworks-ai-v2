# PR #66 — 出图验收、逐张原子证据与恢复

- PR：https://github.com/sqqq2003/solidworks-ai-v2/pull/66
- 代码 pin：`ec606df36a65108d4ff0ec957b8bde18a0884049`
- 代码 tree：`da0f88f5d3e9d1dfa41fcfbaa5883f8049c37c90`
- 独立增量分支：`feat/drawing-visual-evidence-v6`，基于 PR #65，未合并。
- [完整源码测试包](gork-test-kit.zip)：536 个源码文件，含 source.zip、candidate.json、matrix.json、submission-template.json、source-index.json、READ-FIRST.txt。
- ZIP 大小：1,269,994 bytes；SHA256：`4f1ec1916e4647ee568e80014b822c98cbd2ff177d9f35d6b5e3c42d357ce76b`。
- 内层 source.zip SHA256：`db22627914299d36d5916f4b4fcdb083e3f599a80753b8f49fba1bdcf45cf1e8`。

后续仅增加交接附件的提交不是新的代码 pin。回传结果必须使用上面的代码 pin，不能用附件 HEAD 替代。保留原安装、原 CAD、旧候选及旧 pin；只在新目录测试。

## 实际交付

1. `drawing_review.py`：逐张 generating/reviewing/accepted/rejected/failed 状态，哈希绑定的署名四项目视确认、不可覆盖决策、批量检查及脱敏导出。技术成功/pass_pending_visual 不等于 accepted，缺件试图目视接受也不作为生产交付。
2. 现有出图适配器：逐张 flush/fsync/原子 JSON，重开视图、注解名称/类型/位置/文字、比例、BOM/PDF、SHA256 和 MEMBERNOTFOUND 事件。缺 PDF/读回、缺页、失败或未知请求均阻止接受。
3. 试图界面新增实际署名、检查、接受和退回控件，生成操作不自动确认。统一审计对出图 passed 增加人工目视导出门。
4. A01 映射尺寸→检查→图纸/PDF 外套复用 v5 checkpoint；异常恢复隔离副本，核对重开快照及字节。只关闭身份可核对的本次 owned 文档，未知 ActiveDoc 或关闭失败保留现场。无 kill/ExitApp。
5. 两个出图入口复用 v5 幂等回执、SessionLease、跨进程锁与未决隔离；新增实机故障脚本，在实际尺寸 Save3 后或 PDF SaveAs/解析后抛错。

接口、调用示例、窗口行为和故障命令：[docs/drawing-delivery-v6.md](../../docs/drawing-delivery-v6.md)。本轮沿用布局/六格/比例算法及现有建模线，未改 DSL。自动模型恢复接入 A01 映射尺寸出图链路，其它旧整机改型入口未全部接入。

## 已完成的云端检查

- `validation.json` / `targeted-tests.log`：177 项针对性检查，176 通过、1 项历史原件基线缺失跳过。文件、SQLite、竞争与失败恢复采用真实临时文件/子进程；COM/CAD 为 fake。
- `desktop-validation.json` / `desktop-tests.log`：1 项真实 Tk 控件测试在 Linux 虚拟显示通过，原生 worker 为 fake；审核控件完整，生成按钮不写 accepted，按钮没有被窗口裁掉。
- `package-verification.json`：本次完整源码 ZIP 已校验 pin、清单、哈希及矩阵，并安装到新云端目录后复核。未执行安装后源码、安装运行时或启动 SolidWorks。
- 没有全面回归、Windows/SolidWorks 或用户人工目视验收通过结论。

## Gork 本轮三项新增验收

| 检查 ID | 要核对和带回的证据 |
| --- | --- |
| `drawing_visual_acceptance` | D2–D6、A2/A3 × 1:5/1:10/1:20 沿现有出图线验证；保存成功仍 reviewing；署名四项检查后 accepted；旧图/证据改字节、缺件试图、旧 pin 不能冒充交付；回传脱敏 visual-acceptance.json |
| `drawing_atomic_evidence` | 逐页 index 和 JSON；视图、注解/文字、比例、BOM/PDF、MEMBERNOTFOUND 回退/失败；中断只留下完整旧记录，缺页/半报告/PDF 失败均不通过目视门 |
| `drawing_dimension_rollback` | `work/verify_drawing_rollback.py` 两种显式故障点；原件/副本 SHA256、checkpoint、重开快照、FAILED/RESOLVED 回执；外来 ActiveDoc/关闭失败/断连保持未决，不 kill/ExitApp |

`drawings_bom_manufacturing` / `drawing_visual_acceptance` 的 passed 行必须增加 `visual_acceptance: {"path": "visual-acceptance.json", "sha256": "..."}`，并将该 JSON 作为同一行 artifacts。用 `work/drawing_review.py export` 在本机复核当前产物后生成；缺失、reviewing、缺件试图、旧 pin 或不完整检查项保持 review_required。审计通过只表示提交记录一致，工程/制造批准独立。

矩阵保留之前十三项覆盖；新 pin 未重测的项目继续 review_required，不继承旧 pin 的 passed。实际注解枚举、COM IUnknown 身份、引用卸载与实体快照须在目标 SolidWorks 版本验证。
