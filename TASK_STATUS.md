# 任务状态

## GORK-CLOUD-002

- 状态：**完成（模拟）**。Linux 上会话安全测试与发现阶段为 OK。见 `results/cloud/result.json`。
- 分支：`dev/cloud-ai`
- 范围：把云端可运行源码放到本仓库，并在 Linux 上跑模拟测试。
- 实机：不适用。`sw_live=not_applicable_on_linux`。云端不能声称 SolidWorks 已通过。
- 跳过（包里没有对应模块或基线文件，测试文件仍保留）：
  - `test_baseline_hashes_match_uploaded_sources`：没有 `results/cursor/baseline/src` 原件。
  - `tests/test_engineering_controls.py`：没有 `engineering_controls.py`。
  - `tests/test_workbench.py`：没有 `a01.py` / `data/machine_spec.json`。

## 另一条轨道（不在本次云端收口里）

- **A01-002B-1 rework2**：模拟测试 `simulated_pass`。
- SolidWorks **没有**实机测试。
- 等 Codex 另行复核。不要把这条和 GORK-CLOUD-002 的云端结果混成一次实机通过。
