# SolidWorks AI 整体项目测试交接

本轮交付覆盖统一桌面工作台、二维识别、钣金/滚筒/车件计划与生成入口、整机参数预检、串行任务队列、报告和可校验源码包。它不是整机装配/运动/原生工程图均已完成的声明。

## 快速开始

在新的独立测试目录解压源码包，先验证文件清单，再安装到测试虚拟环境：

```bat
py work\verify_test_handoff.py .
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-cloud.txt
.venv\Scripts\python work\project.py doctor
.venv\Scripts\python work\run_cloud_tests.py
.venv\Scripts\python examples\project_smoke.py
.venv\Scripts\python app.py
```

只有 Windows 原生测试还需在该虚拟环境安装 pywin32：

```bat
.venv\Scripts\python -m pip install pywin32
```

GUI 使用 Python 自带 tkinter；Tk 可导入不代表显示器/桌面已经验证。云端仅测试入口可导入与后台合同，未宣称完成 GUI 点击验收。

## 整体模块验收范围

| 模块 | 本轮可以做 | 仍待验证或实现 |
| --- | --- | --- |
| 二维识别 | DWG/DXF 识别；轮廓/孔/折弯、滚筒、车件索引 | 实际 DWG 转换器依赖与复杂客户样图 |
| 钣金 | 计划、K 写入、独占生成、重开与几何核对；已有完整展开管线 | p248 的108/109仍未通过，不能算机械验收 |
| 滚筒 | CLI/GUI 规格计划、生成与重开几何比对 | 所有缺失/推断尺寸需确认；通用默认值非 OEM 测量 |
| 车件 | CLI/GUI 半轮廓和旋转/拉伸计划；正式会话生成、保存码与重开尺寸核对 | 键槽/螺纹等功能的真实完整机械验证；36原始pending合约仍保留 |
| 整机参数化 | 1800×900×1500尺寸图预检，未知OEM保持空，参数CSV | 真实模型映射与整机改型完整验证 |
| 装配/配合/干涉/运动 | 同一工作台显示实际模块状态 | 当前为接口/骨架，不是原生完整装配引擎 |
| 原生工程图 | 工作台显示未完成状态 | SLDDRW/DWG 自动生成未实现，不以其他格式冒充 |
| 桌面/队列/报告 | 一个入口串行操作三类零件与参数化规划；JSON、任务CSV、参数CSV | Windows 桌面及原生全流程实测 |

## 桌面操作

运行根目录 app.py。选择 sheet（钣金）/roller（滚筒）/turned（车件）/parametric（整机参数）。选工作副本后先“加入识别”、再“加入计划”，开始队列查看结果。

- 钣金轮廓从1开始；滚筒/车件规格从0开始。不要与旧零基工作脚本混用。
- 原生生成必须选择本机 SLDWORKS.exe、新 SLDPRT 路径，并勾选已核对识别结果、尺寸和方向。改变输入会取消确认。
- 滚筒缺尺寸默认返回待确认。只有明确允许通用默认值时才勾选对应选项；它不会把这些尺寸写成实测或生产批准。
- “当前任务后停止”只停止后续排队，不杀 Python/SolidWorks，不关闭未知文档。当前任务执行时禁止直接销毁工作台窗口。
- 每个原生任务使用正式独占启动入口，按序执行；不使用 attach shim。任何原生任务失败后停止后续队列，离线识别失败可继续其他离线任务。
- 当前桌面支持零件生成及重开；钣金完整展开/DXF发布请用 work/run_sheet_metal.py，参见 docs/p0-sheet-metal.md。桌面未添加一个虚假的“工程图完成”按钮。

结果在 runtime/project-reports：JSON记录事件、退出码、错误、产物SHA；同名CSV是任务清单，*-parameters.csv只导出真实参数寄存器的条目。未知值为空，不能把任务清单当成已验证的整机BOM。

## 无界面与批量测试

```bat
py work\project.py status
py work\project.py doctor
py src\sw_tool_cli.py --mode sheet --input <图纸.dxf> --profile 1 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.4 --plan-only
py src\sw_tool_cli.py --mode roller --input <滚筒图纸.dxf> --variant 0 --plan-only
py src\sw_tool_cli.py --mode turned --input <车件图纸.dxf> --variant 0 --plan-only
py src\sw_tool_cli.py --mode turned --input <工作副本.dxf> --variant 0 --out <新目录>\part.SLDPRT --sw-exe <安装目录>\SLDWORKS.exe --verify-reopen
py work\project.py batch <jobs.json>
```

examples/project_smoke.py 会建立明确标为 synthetic 的板件/轴/滚筒图，并建立包含五个离线任务的 jobs.json；无需 SolidWorks，可拿生成清单修改路径和参数。默认不从清单执行任意命令，只有受支持模式及明确参数。清单相对路径相对于清单文件解析。批次开始前检查所有命令和重复输出路径，已有产物不覆盖。

任务清单 schema v1：顶层 jobs 数组。零件任务 kind=sheet/roller/turned，action=analyze/plan/generate，source 为本地文件；sheet 需 profile、thickness、radius、angle、k_factor。generate 还需 output、sw_exe、confirmed=true。roller 可选择 allow_inferred=true，明确允许通用默认值。parametric 任务指定 length/width/height，仅离线规划，不自动改整机。

退出码：0表示该命令执行成功，3表示待确认/退化/未完成验收，1表示失败，argparse参数错误通常为2。报告里的 reopen_geometry_verified 仅证明保存后重开的实体重建/尺寸检查，不证明采购件、真实螺纹、配合或运动通过。

## 测试人员回传

回传 HANDOFF.json 的 revision、TEST_RESULTS.json、project.py doctor 输出、GUI 操作错误、任务 JSON/CSV 报告及工作副本产物哈希。原生测试还需正式会话PID证据、SW版本、特征与尺寸读回、重建/保存/重开/展开的逐项结果。客户 CAD 留在本机，不放入源码包。不存在的功能写未实现，没跑的项目写未测。
