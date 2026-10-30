# Windows 回传核对与后续补丁

本批源码基于 PR #66 最新 Windows 兼容补丁 `36630fb8ce4540f03ddb911a160485fcc52f87d9`。复用 PR #67 布局补丁 `82058dea652e069069e2d1ffda0d8b1f2f856535` 的四个源码/测试文件；不合并其原生二进制或历史证据目录，不移动既有测试 pin。

## 回传实际说明了什么

| 回传 | 可确认范围 | 尚不能确认 |
| --- | --- | --- |
| PR #66 Windows Python 3.14.8 源码包，报告 1093 运行/1086 通过/7 跳过 | 报告称离线回归、源包和跨进程锁通过，兼容性补丁已提交 | 未在本云端重现实机；无该 pin 的 SolidWorks/第二台电脑/图纸目视或制造验收 |
| PR #67 DDD，`82058de`，正确开启 auto_layout 的 r2 | A2@1:10、A2@1:20、A3@1:20 三格生成，仍待目视 | 不等于完整 D4、生产图纸或新组合 pin 通过 |
| 同一 D4 的 A3@1:10、A2@1:5、A3@1:5 | 在指定比例下明确返回 layout_does_not_fit_requested_scale，附测量边界 | 不能通过偷偷缩小比例、删除视图或忽略图框校验来报通过 |
| PR #59 D2/D3/D5 与 A2 | pass_pending_visual_review / pass_readback_pending_visual_review | 尚无可转成 accepted 的署名目视决定；D6 仍 blocked/可选跳过 |
| PR #1 旧固定面板 `4b0a986` 的 p248 | 失败仍为失败，历史回传有 108/109 BendRejected、固定面板已锁定但未达 4/4 | 不能移作本批/当前建模代码的测试结论；需要对应源码、原件本机证据继续处理 |

原始核对来源：

- [D4 正式 r2 回传](https://github.com/sqqq2003/solidworks-ai-v2/pull/67#issuecomment-6521383549)。该评论已明确废弃漏开 auto_layout 的第一轮，不能继续引用废弃结果。
- [D2–D6 回传](https://github.com/sqqq2003/solidworks-ai-v2/pull/59#issuecomment-6519617758)。
- [PR #66 Windows 源码包更新](https://github.com/sqqq2003/solidworks-ai-v2/pull/66)。本轮没有新上传的该 pin 实机报告可供验收。

## 已修改

1. 将 PR #67 的 GetOutline/Position 锚点、重建后再测量、有限次数布局收敛和标题栏避让接入 PR #66 的出图验收线；保留比例、图框校验、注解重开核对和 reviewing/accepted 区分。
2. 放不下时抛出 `LayoutDoesNotFit`，附结构化 `sizes_mm`、`outlines_mm`、`sheet_mm`、`scale` 和 `alternatives`。页失败证据及试图 cell 都原子保留这些字段。
3. 备选图幅/比例只做纸面估算并明确要求用户选择、原生复测和目视审核；不再次启动 CAD，不改变当前任务。已知 D4 包络建议 A2@1:10、A2@1:20、A3@1:20，仍不是原生通过结论。
4. 界面区分 3/6 等部分生成，显示明确选择的备选方案，保持 delivery_accepted=false。
5. 保留 Windows 源码包修复：缺少 legacy 时不读取不存在的 baseline、POSIX 指纹路径、UTF-8 子进程读回、跨平台路径断言、Windows Git 临时目录清理及所需桥接/矩阵文件。
6. DXF 打包仅允许已登记的三个合成夹具，而非 dxf_extract 下所有 DXF；不扩大成收集客户 CAD。恢复测试源码的中文注释/滚筒类型字符串，避免乱码使测试走错分支。
7. 符号链接与硬链接拒绝检查拆成独立用例；无符号链接权限会显式 skipped，硬链接检查继续执行，不再默默略过半个用例。

## 接口与证据

`explicit_fit_alternatives(sizes, current_scale, current_sheet)` 复用现有布局函数，输出 A2/A3 与 1:5、1:10、1:20 中能按纸面包络排入的候选。坐标和尺寸均是当前图纸毫米，按比率换算；候选带 explicit_user_choice_required 和 native_and_visual_review_required。

`LayoutDoesNotFit.diagnostic` 可直接 JSON 序列化；`DrawingEvidence.fail` 和 trial `layout_diagnostic` 保留它，`explicit_fit_alternatives` 列出候选。既有异常文本及 ValueError 基类保留兼容。

## 本批验证与交测

只跑布局、出图证据、源码打包、Windows 改动涉及的路径/回执等针对性模拟检查。没有 Windows/SolidWorks、人工目视或全面回归。旧 Windows 1093 项统计属于旧 pin，不附给新源码。

Gork 下轮用一个新的源码 pin/new checkout，先源包/Windows UTF-8 与路径检查，再核对六格 D4、结构化拒绝/显式候选及原子页证据；保留 #66 的目视接受门和 #65 的恢复/幂等/Lease 门。A2@1:10、A2@1:20、A3@1:20 技术结果应重新核对；其余三格必须真实适配，或明确拒绝并给用户选择，不能报全绿。原程序、原 CAD、旧候选不覆盖，不 kill/ExitApp。

建模域的 revision/命名体/间隙/observe/白名单事务仍在独立开发目录，本补丁不把它们计作已交付或已测试。
