# csharp-bridge（Issue #25）

Python ↔ C# SolidWorks 桥接：契约、独立审查、钣金规则核对、最小原型与 mock。

> 证据等级：本目录所有内容属于**离线验证**。C# 代码未在本机编译（无 .NET SDK），
> 未在任何 SolidWorks 上运行；一切 Windows 行为均为 pending_windows_validation，
> mock 通过绝不写成实机通过。

## 目录

| 文件 | 内容 |
|---|---|
| `CONTRACT.md` | 桥接契约：传输、消息格式、独占会话、单位、数组、日志、异常/超时/退出隔离、释放顺序、与 PR #23 的衔接 |
| `REVIEW.md` | 独立审查结论：#15/#19 与 PR #16/#17/#18/#20/#23 的证据现状，已证实 / 待证实清单 |
| `SHEET_METAL_RULES.md` | 钣金规则核对：参数化公式链、K 反推、BA/BD 互验、释放槽规则、缺输入处理 |
| `INTEGRATION.md` | 集成建议（run_plan S1/S2/S5 接入点）、风险清单、Gork 一次性验收矩阵 |
| `src/SwBridge.cs` | C# 桥接服务器骨架（命名管道 + JSON 行协议；默认 mock 模式；RealSwApp 在 `SOLIDWORKS_INTEROP` 后，待实机接线） |
| `src/SwBridge.csproj` | .NET 8 项目文件（mock 模式无需 SolidWorks interop 程序集） |
| `python/bridge_client.py` | Python 侧 mock 客户端（契约实现、单位换算、数组校验、参数化折弯公式、5 步收尾记录） |
| `tests/test_bridge_contract.py` | mock 单元测试（17 项，Linux 可跑） |

## 快速开始（Linux mock）

```bash
cd csharp-bridge
python3 -m unittest discover -s tests -v
```

应输出 17 项全部通过。测试覆盖：契约字段、mm/m 换算、3 点与 16 变换数组往返、
超时、退出码记录（0 与 0xC0000005）、缺 t/K 时 pending（无默认值）、
foreign 文档拒绝关闭、收尾 5 步顺序、checkpoint 记录形状。

## Windows 侧（待 Gork 验收，pending_windows_validation）

```bash
# mock 模式编译与运行（需 .NET SDK，不需 SolidWorks）
dotnet build src/SwBridge.csproj
dotnet run --project src/SwBridge.csproj -- --pipe sw-bridge --mock

# 实机模式（需 SolidWorks interop 程序集 + SLDWORKS.exe，尚未接线）
dotnet build src/SwBridge.csproj -p:DefineConstants=SOLIDWORKS_INTEROP
```

实机验收按 `INTEGRATION.md` §3 的矩阵执行（最小收尾复现、p248 全流程、
oracle 验证、桥接往返、死锁续跑、桥接定性、缺省保护、证据交付）。

## 硬规则（违反即视为本批交付不合格）

1. t、R、K、角度是每单输入，缺失 → `pending_confirmation`，绝不许默认值顶替。
   t=2.5 / R=1 / K=0.36 / BA=3.0 / BD=4.0 只是本厂一次实测用例，非默认值。
2. 收尾 5 步固定顺序：关文档 → 枚举标题 → ExitApp → 逆序释放 → 退出码记录；
   先放引用、最后才 CoUninitialize（Python-COM 路径）。
3. 只关 owned 文档、只退出自己 spawn 的进程；绝不按进程名杀进程、不碰客户原件。
4. 本批只写 `csharp-bridge/` 新目录；不改现有引擎文件，不与 Codex #24 同文件写入。
5. 所有 Windows 行为标 pending_windows_validation；mock 通过不写成实机通过。
