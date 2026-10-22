# 给 Gork / Grok Bot：A01 总协调任务

用户已授权：由 Gork 接管本机执行协调，并合理分派 Cursor。请实际向 Cursor 下发下面的代码任务，等待其结果并检查证据；不要只回复计划。

工作区：
`C:\Users\yue\Documents\Codex\2026-10-22\referenced-chatgpt-conversation-this-is-an\outputs\A01-workbench`

先读工作区 README、`data/tasks.json`、`tasks/Cursor.md` 和上级目录 `A01-001-audit.md`。本任务单已准备，但 Codex 尚未成功通过应用向你投递；接收到本单后才记录为已接单。

## 第一批：实际分派给 Cursor

将工作区 `tasks/Cursor.md` 的完整内容发给 Cursor，告知代码只允许改 `src/`，结果只写 `results/cursor/`。当前 D 盘程序比原 ZIP 更新，`legacy/` 是不可修改的基线，不得退回 ZIP 版本或覆盖 D 盘程序。

把 A01-002B 分为三个串行批次，每批通过后再推进下一批：

1. **002B-1：会话安全。** 去掉按进程名强杀 SW、活动实例内存回收、全局关闭文档等路径；建立任务会话/文档归属与单写入队列。先做模拟测试，确认用户已有文档不受影响。不能证明专属会话时停止 CAD 写入，不得牺牲用户会话来让测试通过。
2. **002B-2：结果和续跑。** 平板降级与完整折弯分开，CLI、GUI、批量报告一致；断点续跑依据源/参数/程序版本/输出哈希及验收记录，而非文件存在。增加针对这些失效条件的回归用例。
3. **002B-3：发布完整性。** 保存返回码和文件检查统一，路径配置化、完整更新清单、可回退发布；明确纯计算、模拟 COM、SW 实机测试边界。未实机验证部分如实留待验证。

同一时刻只给一个 Cursor 代码任务，不同时启动多个 AI 修改 src/。优先请求 Cursor 先提交 002B-1 的补丁和测试记录，避免把整机建模、运动、工程图塞进同一批。

## Gork 自己负责

- 确认 Cursor 实际收到了任务，记录真实会话标识或可核对的回执；不能把窗口打开视为任务已执行。
- 维护 `results/grok-coordinator/progress.md`，记录当前批次、实际派发时间、Cursor 回执、产物位置、测试结果及阻塞原因。
- 检查 Cursor 的修改范围和验收证据。12 项现有工作台测试只验证离线工作台，不能当作旧生成器或 SW 已通过的证明。
- 原程序及原 ZIP 不变；不运行上传安装/注册/覆盖脚本，不关闭用户未保存文档，不修改系统或账户设置。
- 无需等 Cursor 的部分可先做：核对本机环境和图纸清单。若 WorkBuddy 已接入，可将 `tasks/WorkBuddy.md` 交给它，只允许写自身结果目录；本次首要依赖仍是 Cursor 的会话安全修复。
- 原生装配模板、图纸尺寸链和行程范围尚未确认，不得宣称 1800×900×1500 mm 整机已完成或可流畅运动。CAD 写操作须经安全修复验证后，由单一执行者在任务专属会话串行完成。

## 回传格式

先回传“已接单 + Cursor 是否真实接单 + 首批任务 ID”。每批结果写入 `results/grok-coordinator/`，包括：

```json
{
  "task_id": "A01-002B-1",
  "status": "running",
  "cursor_dispatched": false,
  "cursor_receipt": null,
  "changed_files": [],
  "tests": [],
  "evidence_files": [],
  "remaining_issues": []
}
```

示例中的 false/null 是未派发初始状态，必须按实际情况更新。没有回执或没有测试证据时，不得改为 passed。完成后由 Codex 根据文件和证据做集成审查，不自动覆盖生产程序。
