# 让本机 AI 调用 SolidWorks AI

本项目提供模型无关的工具入口。支持 MCP stdio 的 AI 客户端可以直接配置；支持自定义 HTTP 工具的客户端可以使用本地 API。无需修改或绑定特定大模型。客户端仍需支持工具调用，并由用户配置；纯聊天网页不会自动获得本机软件访问权。

## Windows 本机 MCP（推荐）

先安装项目依赖，确认现有离线 CLI 正常。为图纸、输出创建专用工作目录，例如 `C:\SW-AI-Workspace`。在 AI 客户端的 MCP 配置中加入（替换 Python、仓库、工作目录路径）：

```json
{
  "mcpServers": {
    "solidworks-ai": {
      "command": "C:\\solidworks-ai-v2\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\solidworks-ai-v2\\work\\ai_gateway.py",
        "--workspace", "C:\\SW-AI-Workspace"
      ]
    }
  }
}
```

先不配置 `--sw-exe`，验证只读分析和离线规划。要允许原生生成，在上述 `args` 后加入 `"--sw-exe", "C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\SLDWORKS.exe"`。路径以实际安装位置为准。AI 不得通过工具参数选择可执行程序。

可发现的工具：

| 工具 | 用途 |
|---|---|
| `solidworks_capabilities` | 查询真实能力与未完成模块 |
| `solidworks_doctor` | 查看环境，不启动 SolidWorks |
| `solidworks_run_job` | 执行一项分析、规划或已确认的生成任务 |
| `solidworks_batch_review` | 只读识别 DXF 批量候选，返回源/代码哈希与未确认参数，不生成 CAD |
| `solidworks_skill_integration` | 查询原 I01–I08 融合状态；代码存在不等于验收通过 |

客户端先调用能力与环境检查，再分析图纸、检查规划结果。生成前需要明确确认几何与参数；`confirmed: true` 是调用方对确认状态的声明，网关不提供独立人工审批界面。客户端应使用自身工具授权策略控制写操作。

本批未测试扩展支持 `uniform_scale`（正数）与 `preserve_circle_holes`（布尔）传入单件规划/生成。前者只改变平面外形，板厚不跟随；后者仅保持圆孔直径，孔心随外形缩放。曲线与折弯限制仍由现有几何模块检查。本轮没有运行网关、模拟或实机测试，不能视为已验证接口。新增审核工具只接受工作目录内 DXF，不能转换 DWG 或连接原生会话。

示例工具参数：

```json
{"job":{"kind":"turned","action":"analyze","source":"inputs/shaft.dxf"}}
```

```json
{"job":{"kind":"parametric","machine":"GT-ZX","length":1000,"width":800,"height":600}}
```

```json
{"job":{"kind":"sheet","action":"plan","source":"inputs/plate.dxf","profile":1,"thickness":2,"radius":2,"angle":90,"k_factor":0.5}}
```

整机参数规划必须显式提供 `machine`：`GT-ZX` 或 `QL-5050PX`，避免把不同机型混用。此入口暂只暴露整机包围尺寸规划，其他装配/制造专用任务尚未接入工具 Schema。

原生生成将 `action` 改为 `generate`，另加 `output`（工作目录内尚不存在的 `.SLDPRT` 路径）和 `confirmed: true`。钣金 profile 从 1 开始；滚筒、车件 variant 从 0 开始。滚筒推断尺寸需单独显式 `allow_inferred: true`，不能把默认尺寸当作图纸实测值。

## 本地 HTTP 兼容接口

仅在需要 HTTP 的客户端启用。PowerShell 中设置随机令牌，保持令牌私密：

```powershell
$env:SOLIDWORKS_AI_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
python work/ai_gateway.py --transport http --workspace C:\SW-AI-Workspace
```

在客户端设置相同令牌，所有请求带 `Authorization: Bearer <token>`：

- `GET http://127.0.0.1:8765/v1/tools`：工具 JSON Schema。
- `POST http://127.0.0.1:8765/v1/tools/call`：`{"name":"solidworks_capabilities","arguments":{}}`。
- 提交任务：`{"name":"solidworks_run_job","arguments":{"job":{...}}}`。

此 HTTP API 是普通 JSON 工具接口，不是 MCP Streamable HTTP。客户端需要自定义工具适配。服务只监听本机，不附带云端远程访问功能。

## 结果与边界

任务同步执行，CAD 任务可能持续较长时间，应调整客户端工具等待时间。不要因超时自动重试生成；先检查报告和输出，避免重复写入。每次任务结果写入工作目录 `reports/`，含 JSON、任务 CSV 和参数 CSV。

路径只接受工作目录内的相对路径，拒绝目录穿越、绝对路径及解析后越界的符号链接。不要把工作目录设为系统盘根目录或包含秘密文件的目录。网关不提供任意命令、任意文件下载或删除工具。单进程内拒绝并行任务；请只启动一个开启原生写入的网关进程，跨客户端共享 HTTP 实例或串行使用 MCP，原生会话仍受现有所有权检查约束。

`planned`、`analyzed`、`review_required`、`reopen_geometry_verified` 含义与桌面任务一致。重开几何校验不等于机械设计验收。装配、运动与工程图未完成的模块不会因接入 AI 自动变成可用能力。

已验证：两种机型的离线参数真实执行、MCP 子进程握手与工具调用、本地 HTTP 真实请求及令牌校验、模拟原生任务输入绑定与路径防护。新增接口测试 10 项；同步 aca899b 后完整云端回归 525 项，521 通过、4 跳过，跨进程锁检查通过。Windows AI 客户端连接和 SolidWorks 原生生成仍需本机实测。

## 与你正在使用的 SolidWorks 共存

你可以保留自己打开的 SW 和未保存文档。AI 原生任务只绑定它自己启动、且进程句柄与 COM PID 均验证匹配的独立实例；不接管你的实例，不关闭、保存或退出你的文档。如果启动被转发到已有实例、COM 返回了你的实例，或独立实例无法确认归属，任务拒绝写入，不退回到当前活动实例。任务清理只允许退出其归属已证明且没有其他文档的实例。

能力查询返回 `session_policy`，供 AI 客户端读取上述约束。请勿在 AI 的任务实例里打开自己的文档；一旦发现未知文档，执行器阻止后续写入和退出。

进程隔离不等于桌面隔离：独立 SW 可能弹窗、获取焦点，并占用 CPU、显存和许可证。如果要求鼠标焦点和资源完全不受影响，需要独立 Windows 会话或另一台执行机器；本机接口不声称提供这一保证。当前共存保护有模拟回归，仍待 Windows 双实例与未保存文档场景实测。
