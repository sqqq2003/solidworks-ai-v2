# 角色

本仓库是 SolidWorks AI V2 的云端可迁移子集。三方分工固定，不要混用结论。

- **Codex**：派发任务、核对证据、决定是否收口。云端日志不能代替验收。
- **Cursor**：改本仓库（`src/`、`tests/`、`work/`、文档）。云端只跑模拟测试。
- **Grok Bot**：在用户本机做 SolidWorks / 钣金实机核对。云端代理不能代替这一步。

## 云端边界

Cloud Agent 只能跑 **模拟**（假 COM、假进程探针、纯几何导入检查）。

禁止把云端结果写成 SolidWorks 实机通过。实机结论只来自本机 Grok Bot 的证据，并由 Codex 另轨复核。

Linux 上没有 `pywin32`。`win32com` / `pythoncom` 只在真正调用 COM 时导入；导入失败应在调用点报错，不能让 `unittest` 发现阶段崩溃。
