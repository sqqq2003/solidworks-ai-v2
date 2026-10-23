# Issue #6 第二批连续开发

用户要求 Gork 暂时无法测试时继续往下开发。本批沿用只开发、不测试、不排查旧 Bug 的约定；没有运行语法检查、单测、示例、回归或原生 SolidWorks。第一批记录保持原样，新批次追加到同一功能分支和草稿 PR #7。

## 新增实际功能

| 文件 | 可调用入口 | 内容 |
| --- | --- | --- |
| `panel.py` | `develop_panel`、`panel_dxf` | 非矩形 CCW 切线底板、多个独立边法兰、孔、多折弯参数、角部开口间隙、平面轮廓相交拒绝、面积/体积、CUT/BEND DXF |
| `bom_tree.py` | `explode_bom`、`compare_boms` | 嵌套装配数量累乘、可重复子装配、循环拒绝、采购件停止展开、可选含子装配 BOM、版本数量差异 |
| `drawing_layout.py` | `render_sheet_svg`、`annotate_owned_drawing`、`DrawingAnnotationsMixin` | 显式二维视图、水平尺寸、图框、注记、BOM、SVG；独占 Windows 端口原生注记与表格插入代码 |
| `batch.py` | `BatchRunner.run` | 依赖拓扑顺序、跨任务 JSON 结果引用、单写者锁、逐任务失败继续、阻塞传播、输出 SHA256、日志、恢复复用、失败新尝试目录 |
| `manufacturing.py` | `panel_takeoff`、`offline_runner` | 孔扣除面积、外包矩形购料估算、切割长度、折弯数、显式密度/价格质量成本；串联实际模块及待执行原生任务 |

## 调用方式（本批未执行）

```bash
python examples/ql5050px_worker.py examples/ql5050px_pipeline.json --output results/ql5050px-batch2
python examples/ql5050px_worker.py examples/ql5050px_pipeline.json --output results/ql5050px-batch2 --resume
```

示例含参数、带孔双边法兰板、材料估算、嵌套采购 BOM、SVG 工程图和默认 `pending_native` 的原生改型任务。所有尺寸和 7850 kg/m³ 密度只是模拟输入，不写入 QL OEM 映射。

队列任务：`{id, kind, depends_on: [], payload: {...}}`。`{"$ref":"panel"}` 引用依赖任务完整 JSON 结果；`{"$ref":"bom.bom"}` 引用结果字段。必须显式声明 depends_on。可用 kind：parameters、panel、takeoff、bom_tree、bom_diff、assembly、drawing_svg，以及显式开启的 native_variant/native_drawing/native_flat_dxf。

Python 原生接入：`offline_runner(driver=owned_driver, native_port=owned_windows_port).run(jobs,new_dir,allow_native=True)`。仅传 allow_native 不会建立 SW 会话、提供 OEM 映射或绕过已有事务保护。CLI 不提供打开原生执行的开关。恢复必须使用相同 pipeline/version/allow_native；修改任务需新建输出目录。成功任务输出缺失或哈希变化则拒绝恢复，失败任务重试不覆盖历史输出。

## 建模契约与待实现事项

- 边法兰展开输入是切线底板和折弯后直段长度；展开增加 BA+straight，不接受混淆的外模线边长。只支持底板的一层独立直边法兰，不反求任意三维钣金，不含二级法兰、卷边、冲压成形和折弯顺序碰撞。角部间隙为设计参数，制造正确性待实机/工艺确认。
- 平面几何采用浮点阈值，不是精确几何内核。凹多边形、极短边、近共线/近相切需集中验证；孔暂只允许位于切线底板。当前形状相交拒绝不证明实体折叠后无干涉。
- SVG 使用用户给定投影轮廓，不从 3D 自动投影；尺寸仅水平，BOM/notes 溢出时拒绝而非自动分页。还未实现公差、剖视和形位公差。
- Windows 原生注记/表格使用 InsertNote、SetPosition2、InsertTableAnnotation2、IDispatch Text 属性写入，绑定形式未测。结果明确 saved=false；需由独占 host 事务保存和重开核验。固定布局坐标/行数目前需要调用方控制。
- 购料按外包矩形估算，未实现自动排样/余料复用/刀缝补偿。密度和单价由调用方提供；缺值输出 null，不推测。
- 队列的 completed 只表示 handler 返回并记录输出，不代表测试或机械验收。原生验收始终 unverified。handlers 必须是受信任本地代码；队列锁不替代 SW 进程/文档锁。进程崩溃可能留下 .writer.lock 或不完整日志，需保留证据并人工确认退出后恢复，尚无自动抢锁/截断日志。

测试状态：**全部未测**。未修复第一批已知问题。本批继续积累可调用代码，Gork 恢复后再统一验证；无需现在切换其旧项目工作。
