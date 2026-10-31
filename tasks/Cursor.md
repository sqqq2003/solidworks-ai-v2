# Cursor 交接：A01-002B

用户要求由 Codex 协调 Cursor、Grok Bot 和 WorkBuddy 推进 A01 整机参数化计划。本任务尚未在 Cursor 内启动，不要把交接单当作已完成结果。

工作区是本文件上两级的 `A01-workbench`。先读 README、`data/tasks.json`、上级目录的 `A01-001-audit.md`。现有 D 盘程序比 ZIP 更新；以 `legacy/` 为当前版本对照，所有业务变更仅写 `src/`，证据写 `results/cursor/`。不修改 D 盘程序、原 ZIP、`legacy/`、其他 AI 结果或系统配置。

依次完成：

1. 核查并修复 `solidworks_generator.py` 和 `batch_export.py` 的进程名强杀、活动会话重启及全局关闭文档。任务专用 worker、PID/文档归属、一个 STA 写队列是验收目标。无法证明归属的会话必须保留；不能用关掉用户 SW 作为超时恢复。
2. 统一 passed/degraded/failed/review_required。预期折弯但退为平板必须 degraded，CLI 输出 auto_bent、预期/实际折弯数并返回非零的降级码；GUI 和批量摘要也要相符。
3. 断点续跑绑定源文件 SHA-256、参数、程序版本、输出哈希和验收记录；文件非空不足以复用。缺乏重开验收证据的 CAD 输出不能标为完整通过。
4. 统一保存返回码/文件大小/重开检查；不要把自定义螺纹属性当作真实螺纹特征。
5. 路径配置化，更新脚本改为完整清单和可回退发布；固定类型库版本改为实际环境探测，未确认 API 对照官方文档或本机 SDK。
6. 把纯几何、模拟 COM 和 CAD 实机测试明确分开，增加会话归属、超时、降级、参数改变后续跑等回归测试。运行前检查测试内容；不运行原包安装/注册/覆盖脚本，不让测试触碰活动 SW。

先完成无需 CAD 的部分并提交可复核补丁、测试日志及未解决项。不自行安装软件或改变全局 MCP 配置。本次未提供安全的 CAD worker 通道，实机步骤保持待验证，不能虚报通过。

结果输出 `results/cursor/result.json`，至少包含 task_id、status、changed_files、tests、evidence_files、remaining_issues；报告需区分“实现”“模拟测试通过”“SW 实机通过”。不要改共享任务状态，由 Codex 核实证据后合并。
