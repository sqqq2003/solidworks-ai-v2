# DWG 识别任务独占会话修复（2026-10-27）

## 来自上传日志的结论

环境 doctor 两次通过，但明确 `cad_executed=false`。两个车件 DWG 识别任务都在
`analyze_cad_file -> convert_dwg_with_solidworks -> require_model_write` 失败：
`SessionOwnershipError: GetActiveObject/Dispatch alone is not exclusive ownership`。
此时尚未开始零件建模，不能据此判断轮廓、孔、螺纹或尺寸是否正确。
Python 3.14 的 `return in finally` 是另一个已有警告，不是这次任务终止的原因。

## 根因与修改

1. 工作台仅在 generate 动作向 CLI 传 `--sw-exe`，analyze/plan 的 DWG 会丢失用户选定的安装路径。
2. CLI 又排除了 analyze/plan 的 owned-session 包装，导致转换器拿到没有独占证明的 STA lease。
3. 转换器原有 Dispatch/connect_application 路径还会重置已有独占证明，无法正确复用 generate 会话。
4. 导入文档原先到 SaveAs 后才登记；带文档清单校验时，下一次写入保护就会把新导入文档当作未知文档。

现在显式配置安装路径的 DWG analyze/plan/generate 全部在同一个任务 STA/owned launch
上下文运行；转换器只复用已证明的 binding，不 Dispatch、GetActiveObject 或创建第二个连接。
导入后立即登记任务文档，保存改名同步登记，并在失败时也清理该任务文档。
参数属性/方法两种 COM 绑定均可读取。输出必须新建，不能覆盖输入或已有文件。

DWG analyze/plan 也按原生任务使用工作进程超时恢复标记、Windows 限制和失败后停止队列；
不要求生成 SLDPRT、不跳过生成前的审核。DXF 分析不启动 SW；没有指定安装路径时保留
LibreDWG 路线。没有可用独占 SW 转换会话时，错误直接说明配置 --sw-exe / LibreDWG / DXF。

## 验证

新增 12 项模拟合约：DWG 路径传递、CLI 进入 owned scope、生成路径复用同一 binding、
导入后登记、SaveAs 改名、失败导入/保存/文档类型清理、属性/方法读取、外来文档拒绝、
不覆盖、DXF 离线、Windows 限制、原生转换失败后停止队列。

与工作台、sw_session/owned-launch/transaction、转换器、CAD 分析相关回归合计
110 项运行，109 通过，1 项缺历史原始基线夹具跳过；无失败错误。
仅 fake COM/离线几何，SolidWorks 实机未运行。见 delivery/dwg-session-fix/validation.json。

```powershell
python -m unittest discover -s tests -p test_dwg_owned_conversion.py -v
python src/sw_tool_cli.py --mode turned --input "<原DWG路径>" --analyze-only --sw-exe "<安装目录>\SLDWORKS.exe"
```

## Gork 复测与便携包交付

该提交以 dev/cloud-ai @ ac97e2af0a429c86e9ce26f39ac77816f2fd8675 为基线，只有三个生产模块修改：
dwg_converter.py、sw_tool_cli.py、project_workbench.py。原生产安装未被远程修改。

上传便携包记录的 app.py / desktop_ui.py / project_workbench.py / sw_session.py / generator
哈希与本地候选不完全相同，且包含仓库基线未提供的 portable-doctor/app_logging。
因此本 PR 是源码修复，不能整目录覆盖用户安装，也不能宣称已生成可直接替换的便携发行包。
请打包维护者在当前实际发行源码上合入这三处变更，保留诊断/日志/既有实机补丁，
更新 manifest 并产出新目录的独立候选包，记录新代码与包 SHA256；旧包保留。

复测同两张 DWG（先 analyze，不要求生成零件），日志需显示工作进程 native=true，
完整命令带 --sw-exe；独占会话证据须先于识别调用。检查 DXF 存在且可读，原 DWG 哈希未变。
再验证其中一张的 plan，随后经实际几何审核再 generate 到全新输出。
单独对照 DXF analyze 不启动 SW、缺安装路径报错、已有用户会话不被写入或关闭、
转换失败停止原生队列和超时恢复标记保留。未知进程不 kill，未知文档不关闭。
无法证明归属或发生新错误则保留日志/现场，不能靠删除恢复标记继续执行。
验收结果保持 pending_windows_validation，历史轮廓/图纸验收不自动升级。
