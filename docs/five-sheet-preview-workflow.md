# 五图版式预览与失败恢复

工作台的「三视图 / BOM」面板新增「五图版式预览…」。选择已核对分区的五图工作包和新输出位置，点击「生成五图预览」。程序在后台生成钣金图、方管图、明细图、总图、三视图，每张分别存放DXF、PDF、PNG及输出凭据。可用「打开输出目录」查看结果。

本入口只排版已有DXF；不生成三维模型，不读取或批准材料、工艺、尺寸或BOM。预览PDF采用字形轮廓，尚不能完成PDF文字与SolidWorks尺寸的验收关联。结果始终标记`production_approved=false`。业务标题字段、投影法、制造标注和首件需要另验。

任务失败后，选择「恢复失败任务…」，选择原输出目录。程序核对原清单、源图和已完成文件的SHA-256，复用完整且未变的图纸，继续未完成项。若清单或源图变化，需重新核对工作包并选择新输出目录；若已完成输出被修改，程序拒绝自动覆盖。失败的暂存目录和日志保留。输出目录有操作系统文件锁，进程退出或崩溃后自动释放。

每张图先在暂存目录完成保存重开核对和PDF/PNG读取检查，再原子重命名发布。即使进程在发布后、写任务进度前中断，恢复时也可凭输出凭据核对并复用结果。任务状态在`preview-state.json`，逐张凭据在`图名/receipt.json`。后台日志位于程序的`runtime/five-sheet-launches`和`runtime/logs`，可从工作台导出诊断日志。

工程工具可调用：

```powershell
python work/generate_five_sheet_preview.py --manifest "工作包/five-sheet-preview.json" --output "新输出目录"
python work/generate_five_sheet_preview.py --manifest "工作包/five-sheet-preview.json" --output "原输出目录" --resume
```

工作包清单版本为1，必须包含五种图名各一次。每项提供`source`（相对工作包或绝对DXF路径）、`source_sha256`、`groups`（分区到模型实体句柄清单）、`cells`（可见分区到纸空间矩形，单位mm）、`page_mm`（默认594×420）。每个模型实体必须且只能归入一个分区；没有纸面矩形的分区在全部视口内冻结。保留每项输入的原始实体、尺寸及块几何，只复制分区图层和新增纸空间。清单不是自动识别结论，需与实际源文件一起核对。

便携包会检查Pillow、Matplotlib及PDF/PNG实际导出。该诊断不启动SolidWorks，不能替代跨电脑安装、原生工程图、整机或加工验收。软件包不夹带客户工作包或CAD数据。
