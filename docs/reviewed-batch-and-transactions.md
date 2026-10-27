# 逐件审核批量生成与三阶段改型证据

2026-10-28 第二批编码；基于 016fcac，延续“只写代码、不测试”。本说明不构成功能验收或生产批准。本轮没有执行任何下列命令、原生操作或应用启动。

## 桌面审核流程

1. 在“钣金批量预检”选择 DXF 工作副本，查看候选。
2. 保存审核清单后进入“逐件审核”，也可从“逐件审核清单”打开已保存文件。
3. 按零件逐项填写/确认数量、板厚、半径、角度、本单 K、缩放与圆孔策略，填写确认人及包含/排除理由。
4. 点击“确认本件参数与选择”。编辑输入不自动确认；切换零件前会提示未确认输入，保存前要求先确认。
5. 所有候选都要明确包含或排除。疑似文字框只能排除；未确认、失效或缺参数保持阻断。
6. 另存新 JSON，不覆盖旧清单；检查完整性后加入生成队列。
7. 选择输出上级目录，程序预备一个新的批次子目录。此时只创建队列任务，不启动 SolidWorks；仍由用户点击运行。

新路径与原有普通批量导出入口并存。新入口支持每件不同的已确认参数，而非强迫整张图共用一个参数值。原始 CAD 不回写。

## 复用的后台链路

`sheet_review_ui → confirm_job/build_command → run_reviewed_batch → owned_solidworks/run_on_task_sta → execute_reviewed_batch → export_all_sheet_parts → verify_saved_part`

- 确认记录同时绑定源文件字节、审核 JSON 字节、审核内容摘要及任务选项。
- 原生操作前核对源图候选集合、轮廓、文字框分类、折弯线索引与标签，防止编辑 JSON 后换错零件。
- 每件输出到 `profile-N/01×数量 板厚mm.SLDPRT`，目录及输出名由已确认数据生成。profile 身份不接受任意路径。
- 每件复用已有生成器，缩放均从相同源 analysis 开始。要求已证明独占的 STA 与跨进程串行控制；本适配器不接管用户现有会话。
- 当前调用重开验证的范围为实体清单与重建，不包含完整孔槽/折弯几何、材料、公差或生产图纸验收。未给物理方向和尺寸映射时，不猜测包络轴向。
- 任一件失败、退化、会话错误或重开失败停止剩余写入，保留已经存在的文件。
- `execution.receipt.json` 逐件记录 running、saved_pending_reopen、reopened_pending_engineering，以及 unattempted。回执仅原子替换本次新建目录内的任务元数据。
- 原生会话收尾不确定时保留 saved_pending_session_recovery，外围队列将其视为需要恢复的失败；不删除成果、强退进程或伪造通过。

## CLI 与 AI 只读预备

```powershell
# 只输出逐件执行参数与相对输出路径，不创建目录，不启动 CAD
python work/review_batch.py execution-plan --manifest review-confirmed.json
python work/run_reviewed_batch.py --manifest review-confirmed.json
```

独立原生入口要求同时提供 `--execute-reviewed`、当前 `--review-sha256`、实际 `--sw-exe` 与尚不存在的 `--out-dir`。缺少执行开关时永远只预备计划。参数确认属于调用方声明，不是认证或远程授权凭据。

AI 新增只读工具 `solidworks_review_execution_plan`。参数示例：

```json
{"manifest":"reviews/review-confirmed.json","source":"inputs/parts.dxf"}
```

两条路径都必须在配置的 workspace 内；不会跟随 JSON 中任意外部源文件路径。该工具不开放原生执行。现有 `solidworks_run_job` 也没有增加 reviewed_batch action，以免未经主机授权开放新写路径。

## A01 三阶段几何记录

已有 A01 请求可显式新增 `geometry_contracts`。不提供时维持旧尺寸映射路径；提供时必须覆盖全部本批映射参数，且当前只支持 SLDPRT 中的 mm 尺寸。

每项合约需要：

- `confirmed: true`、确认人及带时区的确认时间；这只是审查声明，仍需主机写入授权。
- 与原零件实际字节匹配的 source_sha256。
- dimensions_mm：语义参数键到确切原生尺寸名的映射，必须包含本次修改维度。
- 非空 checks：明确 field、mode、unit、tolerance；target/delta 另需 value。
- 至少一项准确对应本次修改参数和值的 dimension:参数名 target 检查。

`A01ProductionDriver.apply_mapped_dimensions_observed` 复用 Pack and Go 工作副本和现有保存生命周期，将每次改型交给 `change_owned_part`。

1. 验证所有文件映射、确认合约、目标唯一性和原始文件哈希。
2. 仅打开已隔离工作副本；读取配置、实体、包络、体积和指定尺寸，记录 before。
3. 通过原有会话 guard 后写入映射尺寸，重建并采集 after。
4. 将 before/after 与明确目标、差量或不变项比较；缺读回或比较失败不继续保存。
5. 通过已有 `_save` 保存；关闭本次文档后重新打开并采集 reopened。
6. 比较 before/reopened 的目标，以及 after/reopened 的不变性，记录磁盘文件哈希。
7. 任一步失败抛出携带 receipt 的 PartChangeFailed，记录失败位置，不回滚或覆盖原件。关闭结果不确定时不重复 CloseDoc，不强退 SolidWorks。

基线与工作副本还要通过 samefile 检查，避免两个不同路径实际上是同一硬链接文件。包络明确为近似值，记录成功仍为 observations_consistent_pending_engineering，geometry_verified/production_approved 不自动变 true。

此链路不是数据库 ACID 事务：原生 Save3 成功后无法撤销文件写入；若后续失败，保存的工作副本保持未验收，不宣称已回滚。

## 尚未实现或验证

- 未运行模拟、云端、实机、UI 或编译检查；没有本轮通过率。
- 旧版本审核清单的代码指纹会在源码改变后失效；需要按新版本重新识别与确认，暂不自动迁移旧确认。
- reviewed_batch 目前不提供中断后自动续写。普通批量导出原有指纹续跑仍独立存在；本新路径优先保存可复查回执。
- 原生新路径单件期望一个实体，多实体焊件不在此入口中。焊件切割清单、整机配合/运动及生产三视图/BOM仍待独立推进。
- 原生几何事务暂不支持角度、装配体尺寸或自动推断受保护接口；这些情况须使用单独审查过的流程。
- 本轮未生成便携包、未替换桌面已安装程序、未合并到 dev/cloud-ai。
