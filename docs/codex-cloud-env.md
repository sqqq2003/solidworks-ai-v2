# Codex / Cursor 云端环境

建议环境名：`SW-AI-V2-Cloud-Dev`

- Python：3.11 或 3.12
- 分支：`dev/cloud-ai`
- 依赖：只装 `requirements-cloud.txt`（`ezdxf==1.4.4`）。Linux 上不要装 `pywin32`。

```bash
python -m pip install -r requirements-cloud.txt
python -m unittest tests.test_sw_session_safety -v
python work/test_review_session_boundaries.py -v
python -m unittest discover -s tests -v
```

这些命令只覆盖模拟测试。通过不等于 SolidWorks 实机通过。

`src/export_dialog.py` 在导入时使用标准库 `tkinter`。无界面的 Linux 镜像可能没有 `python3-tk`，模拟测试不会加载这个 GUI 模块。

Cursor 目前可能还没有保存好的 Cloud Environment。需要的话由用户在 Cursor 界面里按上面的名字新建；本仓库不能替用户完成那一步 UI 保存。
