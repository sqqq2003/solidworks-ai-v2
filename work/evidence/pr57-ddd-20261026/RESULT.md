# PR#57 全量挂测 · RESULT

- 时间戳：20261026_134308
- SHA：`9544d3ca27b5f4b255b60a3eab3061af8a930fc2`（fix: keep a saved shaft when cleanup inventory drops COM）
- 机器：DDD · 派活：WorkBuddy
- 仓库：`C:\Users\yue\Desktop\solidworks-ai-v2`（已 checkout 9544d3c）
- SW：`D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe`
- 工具链：Python 3.14.8（`C:\Users\yue\AppData\Local\Python\pythoncore-3.14-64\python.exe`），pywin32+ezdxf 就绪，SolidWorks 类型库主版本 33
- OUT：`D:\工程\钣金导入\wb_pr57_full_20261026_134308`

## 各 Ti 状态

| Ti | 测项 | status | 说明 |
|---|---|---|---|
| T1 | 离线 unittest | **pass** | 8/8 OK（PlateBracketCallTests 3 + ShaftRebindTests 5） |
| T2 | 轴 live @ 9544d3c | **partial_pass（目标行为确认）** | SaveAs 写出非空 SLDPRT(62030B) 后 cleanup/inventory COM 断开 → exit 0、status=partial_com_disconnect、路径保留、未 ExitApp |
| T3 | 钣金 live 回归 | **pass** | native_features_verified + sw_live_verified=true；SMBaseFlange/SM3dBend/FlatPattern 特征 reopen editable=true；k=0.36/t=2.5/r=1.0 一致 |
| T4 | 板支架 TYPEMISMATCH 抽测 | **partial** | TYPEMISMATCH 未再现（helper Python 层 TypeError 拦截 str）；但 solid_blind_cut(float) 返回 None（FeatureCut3 未创建） |
| T5 | 车件尺寸对照 | **partial** | f11 锁定柱 PASS（75×19.63×17 命中）；f09/f15/f19 revolve 类生成失败（旋转轮廓不闭合） |

## 结论

**PR#57 核心修复点（T2）目标行为确认有效**：saved shaft 在 cleanup inventory COM 断开时被保留，进程 exit 0、
status=partial_com_disconnect、文件落盘、ExitApp 未调用。轴 live 未宣称 sw_live_verified（诚实）。

**T4 硬化确认有效**：TYPEMISMATCH 未再现，字符串深度被 Python 层 TypeError 拦截。

**遗留问题（非本轮 PR 主题）**：
- revolve 类车件（f09/f15/f19）"旋转轮廓没有闭合轮廓"生成失败，属 turned 轮廓闭合既有缺陷。
- T4 solid_blind_cut(float) 返回 None，FeatureCut3 实体切割特征未创建（选中/返回语义问题）。

## 约束遵守

- 全程只写 OUT 与本派活目录；未写桌面（T5 用 OUT 内适配副本重定向输出）。
- SW 收尾只 CloseDoc；未 ExitApp、未 taskkill（SLDWORKS.exe 保持运行）。
- 诚实 status：轴复测未算 sw_live_verified；T2 标 partial_com_disconnect 而非 pass。

## 产物清单

- OUT\offline_unittest.txt（T1 日志，8/8 OK）
- OUT\accept_T2.json + shaft_9544d3c.SLDPRT + shaft_live_stdout.txt
- OUT\accept_T3.json + sheet_s2\*（part.SLDPRT/flat.DXF/result.json/checkpoints）
- OUT\accept_T4.json + plate_bracket_live.json + plate_bracket_probe.SLDPRT
- OUT\accept_chejian.json + gap_table_T5.md + chejian\f11_锁定柱.SLDPRT
- OUT\RESULT.md + summary.json（本文件）
