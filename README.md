# solidworks-ai-v2

云端分支 `dev/cloud-ai` 放的是可以在 Linux 上导入、并用假 COM 做会话安全检查的源码。这里没有 SolidWorks，也没有 `pywin32`。

**云端测试通过只表示模拟通过。它不是 SolidWorks 实机通过。** 实机钣金 / SW 核对在用户本机，由 Grok Bot 做，Codex 另轨复核。

## 跑云端模拟测试

```bash
python -m pip install -r requirements-cloud.txt
python -m unittest tests.test_sw_session_safety -v
python work/test_review_session_boundaries.py -v
python -m unittest discover -s tests -v
```

日志在 `results/cloud/`。`sw_live` 在 Linux 上记为 `not_applicable_on_linux`。

云端包里没有 `a01.py`、`engineering_controls.py` 和 `results/cursor/baseline/src`。对应测试会跳过并写明原因，会话安全用例仍会执行。

## 布局

- `src/`：从本机工作台迁来的 Python 模块。COM 导入留在调用点，避免 Linux 上 `unittest` 发现失败。
- `tests/`、`work/`：模拟测试与会话边界复查。不启动 SolidWorks。
- `tasks/`：交接说明，不是已完成的实机结果。
- `requirements-cloud.txt`：云端纯 Python 依赖。Windows 锁文件见 `requirements-offline.lock.txt`（含 `pywin32`，不要在 Linux 上安装）。

会话安全补丁的说明见 `README-A01-session-safety.md`。角色和阶段见 `AGENTS.md`、`AI_MASTER_PLAN.md`。
