# 函数驱动参数建模与副本改型

本批基于 PR #69 的 `84bce400c18ad699b1ffe061521668a848fd7b4e`，复用已有参数工作台、依赖排序、ParameterMapping、影响分析、具名审核、sw_api 批量事务、原生尺寸编辑、NativePartHost、检查点与 SQLite 回执。用户母图、原程序、旧测试版本保留，不自动合并。

## 已接通的两条流程

**新建零件**：规则/函数输入 → 带单位计算 → 数值替换到已有白名单特征模板 → 分析与计划 SHA 审核 → 空白模板生成可编辑草图/挤出/切除/旋转 → 命名体与特征检查 → 保存重开、观测证据。显式 `${parameter}` 是数字替换，不执行任意脚本，也不增加新的通用造型 DSL。

**已有零件**：从磁盘原件复制到新目录 → 指定配置的真实线性尺寸读取 → 参数绑定与变化/保护项预览 → 具名确认 → 新的隔离副本内批量修改 → 重建/保护尺寸/树与体数检查 → 保存重开读回。改变源文件、规则、映射、计算结果或实现代码都会使旧审核失效。

桌面启动 `python app.py`，左侧“参数化建模”。工作台有“参数与函数 / 模型与绑定 / 变更预览与执行”三页。SolidWorks 操作通过后台任务与 Tk 主线程队列返回，不在界面线程阻塞 COM。运行期间改输入会使旧结果失效，实际结果仍保存在工作目录；窗口不强杀任务。

## 使用界面

1. 导入规则 JSON/YAML；也可点“编辑函数”，编辑后保存为**新的 JSON 文件**。没有选规则时，编辑器提供 `function-block.json` 示例；内置 A01/滚筒机架规则仍复用原求解器。
2. 输入目标长宽高；额外输入用 JSON 对象，例如 `{"left_end":20,"right_end":35}`。长宽高用 mm，额外参数按规则声明单位。未知值保留缺失；不填 OEM 默认数。计算后显示公式、依赖、单位和目标值。
3. 在“模型与绑定”选择程序、工作目录和方式。
   - 新建：选 PRTDOT 空白模板；规则必须含已有白名单 `feature_template`。
   - 已有：选独立 SLDPRT 和准确配置名，点“读取模型尺寸”。读取的是磁盘副本，原件未保存的内存改动不包含在内。
4. 已有零件点“添加/修改绑定”，选择参数与真实尺寸，填写 editable/fixed/purchased、允许范围及来源。界面范围一律 mm。可导入绑定 JSON，仍须经下一步原生/来源核查。删除绑定代表该参数仅计算；规则声明的保护接口必须绑定，不能删掉以绕过保护。
5. 点“生成变更预览”，核对 before/after、受保护尺寸、未绑定的计算参数、风险、特征计划 SHA；填审核人，勾选确认，再点“审核并执行 SolidWorks 副本”。修改任何有关输入后重新计算/预览。

不要把机架净距 W 当整机外宽。历史滚筒机架规则仍只是待复核输入；本批不把旧母体、旧 GT-ZX 或示例参数当成 QL OEM 实测值。

## 数学规则格式

`kind=parametric_functions`、`schema_version=1`、非空 `source`；`inputs` 定义输入，`parameters` 定义表达式。每项声明 `unit`，可给显式 `range`、来源和 `preserve_interface`。示例见 `examples/function-block.json`、`examples/function-roller.json`。

- 运算：`+ - * / **`、括号；幂的指数必须是无量纲整数 -8..8。
- 函数：min/max（最多16参数且同单位）；abs/sqrt/ceil/floor/round/sin/cos/tan（单参数）。round 是取最近整数；小数位可显式乘除比例。
- 单位：mm、m、mm2、mm3、deg、rad、count、ratio；规范长度为 mm，角度为 rad。长度不能与无量纲常量直接相加，角度不能当长度，sin/cos/tan 输入须为角度；count 必须整数。
- 例如 `barrel_length = length - left_end - right_end`；`hole_count = floor((length - 2*margin) / pitch) + 1`。
- `constraints` 是单次比较，例如 `length > left_end + right_end`；比较失败阻止生成/执行，缺输入则保持未解决。
- 自动从表达式提取依赖，复用既有拓扑排序；未知变量、循环、错误单位、超范围、非有限数、非法函数均拒绝。
- 最多128参数、64约束、每式1024字符/128 AST节点、数值绝对值不超过1e12。禁止属性访问、下标、import、任意调用、lambda、列表推导、赋值或宏。YAML使用 safe_load。

新建特征模板中的数值占位单位与字段匹配：长度/bbox 用 mm（m 转 mm），体积边界用 mm3，面数用 count，旋转角用 deg/rad。未解决输入不允许物化。独立体积/bbox目标来自用户审核的数学规则，草稿估算体始终不当作原生体或制造验收。

## 可调用接口

| 接口 | 作用 |
| --- | --- |
| `parametric_functions.solve_functions(spec, inputs=None)` | 纯数值 DAG、单位、范围与约束；未调用 CAD |
| `parametric_workspace.preview_parameters(..., spec_path, input_values=None)` | 兼容 A01、机架与函数规则，绑定原文件 SHA |
| `parametric_functions.generate.materialize_part_plan(preview)` | 重新按源规则计算并物化旧特征合同，返回 plan 与 SHA |
| `parametric_functions.generate.generate_native_part(...)` | 指定审核人、特征计划 SHA、模板 SHA，在新目录调用旧原生事务 |
| `parametric_functions.api.inspect_native_part(source, configuration, sw_exe, output, request_key=...)` | 独立零件副本上的真实尺寸库存，带原件 SHA 和 inspection SHA |
| `parametric_functions.workflow.prepare_edit_workspace(preview, mappings, inspection, destination)` | 源/计算/映射/原生库存/实现代码绑定，输出变化、保持项和未绑定项 |
| `approve_edit_workspace(directory, reviewer=..., expected_review_sha256=...)` | 复用既有审核合同，原子且不可覆盖的具名记录 |
| `parametric_functions.api.execute_edit_workspace(..., approval_sha256=..., request_key=...)` | 复用设计审核、批量事务和 `edit_reviewed_length`；原生保存重开与完整回滚 |

`.api` 的 inspect/apply 与生成入口均复用全局 STA/OS 写锁、durable 请求回执。同 key/相同 payload 返回旧结果而不插入/修改第二次；不同 payload 冲突，RUNNING/OUTCOME_UNKNOWN 等先对账。已确认无参数写入且清理正常的读取/前置失败记录 FAILED/RESOLVED；超时、断开、外来文档和回滚不确认继续隔离。

每步改尺寸前绑定当前 revision。参数编辑使用同一个整文件检查点；中途尺寸失败、保护尺寸被联动改变、原生树/体数改变、保存/重开错误均恢复字节并重开校验。若写前发现手改 revision 冲突，则保留现场不覆盖，进入未决。检查点包含工作模型字节和原件 SHA；只清理自有 manifest，不扫描/删除用户 CAD。

## 命令行

云端可完成：

```console
python work/parametric.py preview examples/function-block.json --length 80 --width 30 --height 10 --out block-preview.json
python work/parametric.py materialize block-preview.json --out block-features.json
python work/parametric.py preview examples/function-roller.json --length 800 --width 1 --height 1 --out roller-preview.json
```

滚筒示例未声明 width/height，因此该条的两个占位 UI 维度不参与规则，不能写成模型宽高测量。示例计算筒身745 mm，孔数9，居中边距44.4 mm，均非 OEM 证据。

Windows PowerShell（路径换成本机真实值；只用新输出目录）：

```powershell
$sw = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe'
python work/parametric.py inspect 'D:\models\Part.SLDPRT' --configuration 'Default' --sw-exe $sw --out 'D:\SWAI-test\inspect-001' --request-key 'parameter-inspect-001'
# 按实际 inspection.json 确认 model-mapping.json，包含文档/配置/特征/尺寸/来源/范围和保护角色。
python work/parametric.py prepare block-preview.json model-mapping.json 'D:\SWAI-test\inspect-001\inspection.json' --out 'D:\SWAI-test\review-001'
$review = Get-Content -Raw -Encoding UTF8 'D:\SWAI-test\review-001\impact.json' | ConvertFrom-Json
python work/parametric.py approve 'D:\SWAI-test\review-001' --reviewer '审核人' --review-sha256 $review.review_sha256
$approval = Get-Content -Raw -Encoding UTF8 'D:\SWAI-test\review-001\approval.json' | ConvertFrom-Json
python work/parametric.py apply 'D:\SWAI-test\review-001' --sw-exe $sw --approval-sha256 $approval.approval_sha256 --out 'D:\SWAI-test\edit-001' --request-key 'parameter-edit-001'
```

新建：

```powershell
$features = Get-Content -Raw -Encoding UTF8 block-features.json | ConvertFrom-Json
$template = 'D:\templates\empty.prtdot'
$templateSha = (Get-FileHash -Algorithm SHA256 $template).Hash.ToLower()
python work/parametric.py generate block-preview.json --sw-exe $sw --template $template --template-sha256 $templateSha --reviewer '审核人' --reviewed-plan-sha256 $features.plan_sha256 --out 'D:\SWAI-test\generated-001' --request-key 'function-generate-001'
```

CLI 数值预览/物化成功返回0；原生结果或审核待复核返回3，失败返回1。成功读取、Save3、保存重开和数值/特征符合都不等于 accepted，不给制造放行。

## 会话与已有程序

本条新流程的 `session_mode`：

- `auto`：无匹配实例时自行打开；唯一匹配实例必须已空闲，检查两次无文档后复用；多实例或已有文档则明确拒绝，不猜 PID、不关闭文件。
- `idle_existing`：只允许唯一空闲实例，不启动第二个进程，适合 Gork 验收机。
- `dedicated`：用户明确选择独立实例，保留其他程序与文档；按旧 owned PID/进程句柄证明归属。

统一验收器仅对本批四个 parameter native 项接受严格空闲复用记录，要求两次空闲证明、PID/query-handle策略、未关闭外来文档及清理无异常；其他原生项保留原会话门。收件通过仍只是记录/文件核对，不代替独立实机或工程验收。

复用空闲会话期间若出现未拥有的文档，保持打开、阻止写入，不能把“装配体1”这样的名字当授权关闭依据。CloseDoc只针对本任务的副本，不 ExitApp、不杀进程。#69 旧原生验收入口的 attach/CloseDoc 策略没有在本批改写；新函数工作台与 CLI 始终显式走上述严格会话合同。不要将旧入口结果混入新功能验收。

## Gork 统一验收

矩阵新增1项 offline、4项 native，总26项，不要求打断旧任务逐个验收：

1. `parametric_function_units_and_dependencies`：两示例、m/mm和角度换算、缺输入、依赖环、非法代码、范围/接口约束、输入变更后旧审核失效。
2. `parametric_generated_feature_part`：工作台和 CLI 各生成一个80×30×10的可编辑块体；核对目标特征、命名体、面数、体积/bbox与保存重开。平面本地名称先明确映射后重做预览。
3. `parametric_existing_part_batch`：从真实零件读取并确认2至3个独立 driving 线性尺寸，至少1个保护尺寸；改副本、重建、保存重开读回、树/体数、原件 SHA。外部引用/装配/角度/计数写入须拒绝，不能填伪通过。
4. `parametric_review_and_request_replay`：具名确认、原件/规则/映射/代码改变后的拒绝，同key重放/冲突、超时隔离，auto打开/唯一空闲复用；已有文档与多实例拒绝时没有 CloseDoc/新进程副作用。
5. `parametric_saved_batch_rollback`：用独立副本和新 key 运行以下显式故障；确认已保存修改过的字节最后恢复到 manifest 基线、保护尺寸和重开库存一致、FAILED/RESOLVED，原件 SHA 未变。

```powershell
python work/verify_parameter_edit_rollback.py 'D:\SWAI-test\review-001' --sw-exe $sw --approval-sha256 $approval.approval_sha256 --out 'D:\SWAI-test\fault-001' --request-key 'parameter-fault-001' --session-mode idle_existing --enable-fault-injection
```

故障工具在真实修改批 Save3 成功后主动抛错，复用事务恢复，写 parameter-edit-rollback-fault.json；成功验证仍为review_required/退出3。未知/未决会话先用已有 `work/delivery.py` 安全对账，不直接重放或重启进程。

回传固定源码 pin、环境版本、会话 PID/句柄证据、实际退出码、阶段 JSON/日志/截图及 SHA。分类 passed/degraded/failed/review_required；旧版本测试不能给新 pin 销项。客户 CAD/模板保留本机，不进源码包。

## 当前范围与未测项

- 原生已有模型编辑只支持**独立零件、一个配置、最多64个正值 driving 线性尺寸**，单位mm/m；受驱动/只读尺寸不能写。角度与孔数可参与计算，但本批不写原生角度/计数。
- 函数本身最多128参数；新建特征仍复用旧32步白名单。参数函数不等于任意几何函数曲线、任意 Python 插件或自动整机拓扑求解。
- 装配关联改型、多文件/外部引用、配合/运动/工程图/BOM自动联动仍沿已有独立模块验收，本批不宣告这些已自动闭环。
- 原生 bbox 近似，树/体数、映射读回与保护项是技术检查；仍需工程师核对设计意图、公差和制造。新/旧模型均不自动签发 accepted。
- Linux仅能做数值/模拟COM、真实临时文件/SQLite和实际虚拟桌面控件检查，不能代替Windows/SolidWorks实机。本批不重复全面回归或修普通旧Bug；旧观察错误测试缺少Windows模拟前置条件，仅补其测试夹具，不放宽运行时门禁。
