# SolidWorks AI V2

项目工作台覆盖二维 CAD 识别、钣金/滚筒/车件入口、整机参数预检、串行任务与报告。原生 SolidWorks 操作仅在 Windows 独占工作会话执行；Linux 测试只证明离线算法和模拟合同。

```bash
python -m pip install -r requirements-cloud.txt
python work/project.py doctor
python examples/project_smoke.py
python app.py
```

app.py 需要桌面与 tkinter。Windows 原生生成另需 pywin32、SolidWorks 与 --sw-exe 正式会话入口。

- [整体项目测试与交接](docs/project-testing.md)：桌面、三类零件、批量任务和测试回传。
- [钣金实机联调](docs/p0-sheet-metal.md)：独占进程、K因子、展开与p248未解决项。
- [整机参数预检](docs/a01-parametric.md)：真实OEM未知值保持pending，不冒充整机完成。

```bash
python work/run_cloud_tests.py
python work/project.py status
python work/project.py batch runtime/whole-project-smoke/jobs.json
```

装配配合/干涉/运动、原生工程图目前仍有骨架或未实现部分，工作台如实显示。36项原始pending特征合约不计通过；重开尺寸验证也不等于机械验收。

源码测试包可用 work/prepare_test_handoff.py 创建，校验入口为 work/verify_test_handoff.py。不包含客户CAD、凭据、原生产程序和原生实机通过承诺。请在独立目录测试，不自动覆盖用户D盘程序。

## AI 客户端调用

新增本机 MCP stdio 与带令牌的本地 HTTP 工具接口，可供支持工具调用的不同 AI 客户端接入。参见 [Windows 接入配置与示例](docs/ai-client-integration.md)。默认仅分析/规划，原生生成需要主机显式启用。

统一源码候选、方案审核工作区和 Gork 证据收件入口：[交付说明](docs/unified-candidate.md)。
