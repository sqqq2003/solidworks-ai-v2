# 项目运行、问题归纳与后续代码（2026-10-24）

## 实际执行

- 桌面工作台已启动，进程窗口响应已核对；环境具备ezdxf、tkinter、pywin32、comtypes。
- examples/project_smoke.py实际执行：识别1项、计划2项、待审2项；不是原生CAD生成验收。
- QL integrated实际生成BOM、任务矩阵、OEM缺口及交接包。work/check_issue13.py的端到端、产物哈希、禁止覆盖、冲突目标拒绝和桌面/批量共用命令检查全部通过。
- 声明式制造队列首次运行及resume：5 completed、0 failed、0 blocked、1 pending_native。原生禁用项没有计作通过。
- 最新完整离线441项：436通过、0失败/错误、5跳过，跨进程锁通过。C# Python合约另17项通过，模块未变未重复运行。36项pending功能合约不算通过。

## 已修复并继续编写

此前def70f3已修Windows恢复锁误用os.kill(pid,0)终止进程的问题，改只读句柄查询。本批顺着运行结果继续修复QL批量续跑：

1. 日志中的value必须与已核验哈希的result.json内容一致，避免下游复用被修改的数据。
2. completed条目必须有本任务唯一result.json，空产物及kind不符拒绝复用。
3. $ref返回独立数据副本，防止下游处理器原地修改上游已记录结果。

新增5项回归：旧实现明确复现3项续跑错误及1项引用别名错误；修复后5项全过。正常续跑不重新运行已完成任务，保持复用已有计算。

## 未通过/未验证/阻塞

| 项目 | 真实状态 | 下一步 |
| --- | --- | --- |
| p248 108/109 | 最后可核实折弯结果仍2/4 | 按ur56w8仅做原生oracle，不整跑step0；拿原始稿确认类型、SAFEARRAY与坐标布局 |
| oracle交接稿 | 本机指定HANDOFF及该次原始JSON不存在；仅有任务摘要 | 已请求现有Cursor/Qoder执行者共享可读分支或Crosswalk文件，不能猜测修复成功 |
| C#编译/原生桥 | dotnet host存在，dotnet build实际失败：No .NET SDKs were found | 配置SDK后编译；真实pipe、RealSwApp和进程退出另验收 |
| OEM/机械参数 | 未映射与未确认值仍pending | 来源、单位、范围确认后再接入，K不设通用默认值 |
| WorkBuddy/Qoder双轨选型 | a9rpk4仍未验收，不引用外部501/473文档值冒充本轮测试 | 单一主干接口审查及未推补丁合并另轨推进 |

模拟、原生软件行为、机械制造验收保持分开。当前无新增SW实机通过声明，原CAD和D盘程序未改写。

下一批优先处理原生oracle交接稿和SAFEARRAY接口审查；已启动的原生任务先收证据，不重复派发、不并发写CAD。离线问题继续按检查→修复→测试→提交闭环。
