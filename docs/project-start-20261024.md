# 2026-10-24 项目启动与联合测试批次

基线 d392b74；本轮启动 app.py 工作台，并实际运行 examples/project_smoke.py 和 work/project.py ql --action integrated --config examples/ql5050px_integrated.json --output-dir <新目录>。样例属于 synthetic/offline，OEM映射保持pending，机械验收未完成。

## 合并验证内容

1. 生成折弯线前自动与同一独占会话的原生 MathPoint.MultiplyTransform 对照，错位/离面立即阻断，不再依赖人工对日志；不接管新会话。
2. 每个分组带 native_attempts：select_sketch、select_fixed_face、insert、rebuild阶段、返回None、原生特征错误码和异常类型。失败JSON保留完成数、失败编号与完整分组证据。
3. work/run_sheet_metal.py 新增 --no-relief-retries：step0单次生成，禁止扩槽与平板回退；仍复用既有重开/特征/展开/DXF管线。
4. work/check_sheet_metal_evidence.py <report.json> 只读检查参数计划、独占会话、完整折弯、重开读回、两个文件哈希及进程退出码；输出evidence_consistent仅指记录一致，不代替机械验收。
5. 恢复锁的Windows进程探针改为OpenProcess(SYNCHRONIZE)+WaitForSingleObject(0)，彻底避免os.kill(pid,0)终止锁持有者。Linux探针保持原语义，未知权限不当作已退出。
6. Windows路径断言和缺COM用例改为跨平台、确定性的测试；新增可选的逐模块隔离测试入口 work/run_isolated_tests.py。

## 实测

完整离线436项：431通过，0失败/错误，5跳过；跨进程锁通过。C#桥接Python合约另17项全部通过，未运行C#编译或原生桥。依赖为ezdxf1.4.4、pywin32 312、comtypes1.4.17。工作台窗口响应已从进程信息核对。证据results/cloud/project-start-20261024.json。

## Gork / WorkBuddy 一次联合回传

沿用原任务，串行执行：先确认完整提交与实际加载模块哈希，再桌面doctor/三类零件演示/QL整合入口，最后正式独占SolidWorks会话的p248单次测试。--profile在run_sheet_metal中是零基，因此p248用247；不要混用旧CLI的一基248。

所有t/R/angle/K/方向须来源已确认，K未确认必须保持pending，不能填通用值。参数明确后运行work/run_sheet_metal.py <工作DXF> --profile247（实际命令空格写作 --profile 247） --no-relief-retries --live及其显式参数/--sw-exe，把完整stdout JSON存入新的输出目录，再运行check_sheet_metal_evidence.py。失败先回传诊断，不重复跑三轮加深。4/4还需要重建、保存关闭重开、展开、完整产物哈希和正常退出。

不覆盖母CAD或D盘程序，不并发写CAD，不结束未知会话，不往桌面写文件；坐标/客户图纸仅留本机，公开记录脱敏。
