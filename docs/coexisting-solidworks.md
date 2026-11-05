# 已有 SolidWorks 窗口时自动另开任务实例

原生建模验收（`run_native_modeling`）不使用本模式。它只附着到一个已经打开、且可执行文件路径匹配的 SLDWORKS，只 CloseDoc 本任务新建的文档，不另开进程，不调用 ExitApp，不结束进程。下面描述的仍是其它需要独立任务进程的入口。

用户可以继续保留现有 SolidWorks 窗口，AI 自动启动一个新的 SLDWORKS.exe 进程。
“独占”只表示 AI 只操作本任务启动且验证过的实例，不表示整台电脑只能开一个 SolidWorks。
新旧窗口共存仍需本机安装和许可支持；云端不把模拟测试当成实机可用性验证。

## 实现

- 移除整合版 owned_solidworks 中“已有 COM 注册实例则不启动”的过严预检。
- 仍使用 WindowsProcessLifetime 启动新进程并保留进程句柄，核对可执行文件及进程存活。
- 查找 ROT 中该新进程的 SolidWorks_PID_<pid> 项，随后核对 GetProcessID。
  忽略其它窗口的 ROT 项，不调用其 GetObject，不使用全局 GetActiveObject 抢占活动窗口。
  Dispatch 参数只可以是选中的现有 ROT 对象，不是用于启动程序的 ProgID 字符串。
- 新进程文档清单、任务 STA、写锁、保存/重开和已有锚点文档生命周期规则保留。
- 如果新进程退出、实际连接 PID 不匹配、出现未知文档或注册超时，则保留现场并报告原因，
  不改用旧窗口、不关闭用户文档、不按进程名结束程序。
- session 证据新增 instance_mode=new_process_alongside_existing，
  connection_policy=spawned_pid_rot_only；桌面设置说明会另开任务窗口。

同时复用 PR #61 的 DWG 修复：分析/计划传 --sw-exe，在同一已证明任务会话内转换，
导入后立即登记文档、跟踪 SaveAs 改名，失败也清理任务文档。
原生 DWG 分析使用超时恢复标记/失败停止队列；DXF 分析不启动 SW。
本分支基于 PR #56 完整桌面/多服务 API 候选，在其现有源码上修改，未覆盖 dev/main、旧测试pin或用户安装。
不需要为了获得这两项修复把旧 dev 目录整体覆盖到便携包。

## 离线检查与实机复测

相关模拟/离线测试 129 运行、128 通过、1 缺历史基线夹具跳过；实机 not_run。
5 项共存/发现测试直接覆盖：旧 ROT 在前仍选新 PID、前缀相似 PID 不误选、
无目标时不接管旧窗口、名称匹配但 PID 错误拒绝、不可读旧项不阻断新实例、
旧实例存在仍调用启动器并完成本任务绑定。
另复用 DWG、会话安全、任务队列、锚点生命周期和 CAD 分析检查。
脚本为 tests/test_owned_launch_preflight.py（原来的拒绝已有窗口测试已更新为新行为）。

Gork 在新候选目录打包并复测：

1. 先开用户 SolidWorks 窗口，保留一份未保存的测试文档，记录旧 PID/文档名。
2. 在 AI 设置选择安装路径，执行 DWG analyze。应自动出现第二个任务进程，
   session.pid 与旧 PID 不同；旧窗口和未保存测试文档不被修改、保存或关闭。
3. 再做 plan、审核后 generate 到新文件；核对 DXF、零件保存重开、尺寸与原 DWG 哈希。
4. 运行完成或失败后复核旧窗口/文档；只按既有所有权和生命周期规则收尾任务实例。
5. 分别测没有旧窗口、两个旧窗口、任务注册超时、第二实例无法启动、未知文档出现，
   以及 DXF 离线分析。失败不能回退到用户实例。

当前上传便携发行包与仓库源码哈希不同。打包维护者需合入这些增量并保留现有诊断/COM补丁，
更新 manifest、产出新目录候选包后再给用户替换使用；本 PR 不代表用户已安装版本已更新。

参考官方 [SOLIDWORKS API SolidPractices：获取 ISldWorks 指针](https://3dswym.3dexperience.3ds.com/wiki/solidworks-news-info/getting-started-with-the-solidworks-api-solidpractices_eLpSxUm2THqG6jwQdSrMGQ)：
Process.Start 打开程序后，通过 ROT 与进程 ID 定位正确的自动化对象。
