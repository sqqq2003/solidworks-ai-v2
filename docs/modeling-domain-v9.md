# 有界建模域与实机交接（v9）

本批在 #68 代码 `d029305b3aa19aa0b41b72a1505c6579d3828921` 上继续开发，保留其出图布局、原子证据和目视验收门。原安装、用户 CAD、旧 pin 不覆盖。不合并二进制历史；本批不宣告任何 SolidWorks、工程或制造验收通过。

## 实际接口

| 接口 | 实现与边界 |
| --- | --- |
| `modeling_domain.analyze_draft(plan, revision=None, inventory=None)` | 复用已有单位、依赖、草图验证；闭合轮廓面积/扫掠体积估算，自交、开口、旋转跨轴检查。估算不是原生体或验收；复杂弧线草图暂拒绝原生准入。 |
| `modeling_domain.run_transaction(plan, port, expected_revision=..., reviewed_plan_sha256=...)` | 最多 32 特征、每草图 256 元素，草图/挤出/切除/旋转白名单；先检查点，再逐步写、重建、原生类型和命名体检查，保存重开再核对。 |
| `modeling_domain.api.run_native_modeling(...)` | 新目录、附着到一个已打开且路径匹配的 SLDWORKS（不另开进程）、CloseDoc-only、已有 STA/OS 锁/SQLite 回执；明确模板 SHA256 和已审核 plan SHA256。仅接受只有原点/基准面的空白零件模板，不改用户现有模型，不调用 ExitApp，不结束进程。零个或多个匹配进程时拒绝。 |
| `modeling_domain.edit_compatibility(inventory, owned_features)` | 输出受保护或未知特征；仅附加自有命名特征，不删除、抑制、修复陌生拓扑。 |
| `modeling_domain.observe(port, expected_revision=..., directory=..., camera=...)` | 四个白名单视角，原始相机对象与数值还原，版本前后校验、BMP SHA256、原子 observation.json。只进入 reviewing。 |
| `modeling_domain.body_clearance(port, left, right, expected_revision=...)` | 校验真实体有效性，真实体 `ClosestDistance`，两份 `Copy2(False)` 后求交，不将原体传入破坏性 Boolean。只有 separated/interfering/unknown；失败、空返回、矛盾数据、接触公差区都不是零间隙通过。 |
| `cad_domains.get_adapter('modeling'|'sheet_metal')` | 建模调用上述实际接口；钣金复用 `sheet_metal_pipeline.build_plan/run_plan` 和 `WindowsSheetMetalPort` 的基体、折弯、重开、展开、DXF 实现，不重新搭建通用 DSL。 |

`NativeModelingPort` 复用 `NativePartHost`、typed 特征调用、已有文件检查点。每步要求独立的命名体集合、最小面数、体积上下界及 bbox；bbox 为原生近似包围盒，不代替精密尺寸测量。库存按名称/原生类型映射核对，允许返回顺序变化和草图被吸收为子特征，禁止偷偷多出宏特征等对象。

文档 revision 绑定文件 SHA256、活动配置、特征/体库存和未保存状态的 update stamp；干净重开不因临时 stamp 不同而误判。每步写前检查，发现手改即停止；事务中途 revision 冲突保留现场、进入 OUTCOME_UNKNOWN，不覆盖手动改动。普通写入或读回失败恢复整份检查点字节，并重开核对库存与 SHA256。关闭来源不明的 ActiveDoc、还原未确认或 COM 会话异常都保持隔离，CloseDoc-only，不退出或杀 SolidWorks。

共享 `cad_run.run_receipted_cad` 从已有出图 runner 提取，出图仍保留原状态策略；建模只在原生读回完成、原模板未变且 owned 清理确认后封存回执。相同请求重放返回旧结果，不重建零件；同 key 改 payload 冲突；未决请求先按已有 `work/delivery.py reconcile --key <request-key>` 对账，不盲目重跑。两域的恢复合同明确区分：旧钣金适配器保留原分阶段恢复，不声称自动获得本批实体建模检查点。

## 调用示例

云端可执行的分析：

```console
python work/modeling.py capabilities
python work/modeling.py analyze examples/modeling-block-v9.json --out analysis-block.json
python work/modeling.py analyze examples/modeling-cut-v9.json --out analysis-cut.json
python work/modeling.py analyze examples/modeling-revolve-v9.json --out analysis-revolve.json
python work/modeling.py analyze examples/modeling-two-bodies-v9.json --out analysis-two-bodies.json
```

Windows PowerShell，先读分析结果、审核具体几何与体积/bbox，再执行新目录。`Front Plane`、`Line5` 是示例映射；本机语言或命名不同应先修订计划并重新分析、审核，不自动猜测。

先手动打开一个与 `--sw-exe` 相同路径的 SolidWorks，并关掉其它 `SLDWORKS.exe`。验收只附着这一个进程，不另开，不调用 `ExitApp`，不结束进程。零个或多个匹配进程都会直接拒绝。附着后对 ActiveDoc 和 GetDocuments 循环 `CloseDoc`，直到连续两轮没有任何文档（已 `NewDocument` 且登记为本次任务的那一份可以留下）。写入过程中若再冒出未拥有标题（例如会自动重开的「装配体1」），立刻再 `CloseDoc` 一次；仍然在就拒绝写入，并在错误里带上标题和 `GetPathName`。进程保持打开。

`SelectByID2` 的 Callout 看 pywin32 包装，不看修订号：`win32com.gen_py` 早绑定传 Python `None`（Qile3 上 `pythoncom.Nothing` 和 `VARIANT(VT_DISPATCH, None)` 都会报不能转换成 COM 对象）；晚绑定 `CDispatch` 传 `pythoncom.Nothing`（裸 `None` 类型不匹配）。第一次编组失败才换成另一个，只换一次；返回 False 不重试。`GetErrorCode2` 走晚绑定，避免早绑定 `_ApplyTypes_` 里 `int(VARIANT)`；`Save3` / `GetUpdateStamp` 在 `int` 之前解开 VARIANT。凸台拉伸的 `GetTypeName2` 接受 Boss、BossExtrude、Extrude、Extrusion、Boss-Extrude，以及中文环境的「凸台-拉伸」「凸台拉伸」「基体-拉伸」「拉伸」；空格、连字符和斜杠不参与比较。通过或拒绝都把实机原文字符串放进 `native_type`。本仓库未把这次改动再跑一遍 Windows 实机。

```powershell
$sw = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe'
$template = 'C:\your-templates\empty.prtdot'
$templateSha = (Get-FileHash -Algorithm SHA256 $template).Hash.ToLower()
$draft = Get-Content -Raw -Encoding UTF8 analysis-block.json | ConvertFrom-Json
python work/modeling.py run examples/modeling-block-v9.json --sw-exe $sw --template $template --expected-template-sha256 $templateSha --reviewed-plan-sha256 $draft.plan_sha256 --request-key 'v9-block-001' --out 'C:\SWAI-tests\v9-block-001'
```

成功读回仍返回退出码 3（待审核），失败为 1；分析成功为 0。重放相同命令返回回执，不插入第二份特征。更改视角等 payload 却复用同 key 必须报 IDEMPOTENCY_CONFLICT。需要新建试验时换 key 和输出目录。`run` 生成原子分析/逐步证据、检查点 manifest、模型、保存重开库存、BMP 与 observation.json、native-result.json。控制台结果带最终 durable 回执；native-result.json 为其封存前的原生结果。

多体示例用自身分析 SHA 执行，增加 `--clearance AI_Main AI_Second`。Boolean 对无交集返回错误或 NULL 时本版本保守返回 unknown，即使距离测量可读，也不将 Boolean 失败当作 0。单个状态不能授予工程或制造通过。

显式故障测试：

```powershell
python work/verify_modeling_rollback.py examples/modeling-block-v9.json --sw-exe $sw --template $template --expected-template-sha256 $templateSha --request-key 'v9-rollback-001' --out 'C:\SWAI-tests\v9-rollback-001' --fault-after-feature AI_Boss --enable-fault-injection
```

该工具在指定真实特征创建、重建和保存后主动抛错，核对回滚 manifest、工作模型/模板字节和 FAILED/RESOLVED 回执，写 `modeling-rollback-fault.json`。必须新目录、新 key；不得在母图上测试。工具成功完成回滚核对也返回 3 待人工复核。

## Gork 新增五项，统一回传

候选矩阵增加五个 native 检查，总 21 项（既有检查不代替本批新增检查）：

1. `modeling_named_bodies_and_features`：四个示例，计划与实际特征类型、名称、每体面数/体积、整体 bbox、保存重开与编辑性。旋转明确 mark 16、命名构造轴；本机版本不支持时如实 blocked/failed，不猜轴或换造型。
2. `modeling_half_build_rollback`：运行上述故障工具，保存后的半成品确实改变过，失败后完整基线恢复、SHA/库存重开一致，模板未改。外来 ActiveDoc 情形拒绝字节替换。
3. `modeling_revision_and_observation`：原生端口分析后手动改尺寸或特征再用旧 revision，写入次数应为零；事务中途手改应隔离、不覆盖。验证相机数值还原、BMP/JSON hash 与 revision，截图实际目视，reviewing 不能报 accepted。
4. `modeling_body_clearance`：分离、真实重叠、接触或误差区、Copy2/Boolean/距离接口失败。核对原体和模型文件未变，失败明确 unknown。正常分离但 Boolean 无结果也不能填 0 假通过。
5. `modeling_request_replay_and_quarantine`：同请求重放不插特征、同 key 不同 payload 冲突、超时/COM 断开/回滚不确认后禁止新写，沿已有安全对账恢复，不杀进程。

回传填写实际 source pin、Windows/Python/SolidWorks 版本、附着到的 PID 与只读查询句柄（不另开进程）、原子 JSON/日志/BMP 的相对路径与 SHA256；截图含用户模型时留本机或按已授权范围回传，不把 CAD 和模板打进源码包。新组合测试不能引用 #66/#67/#68 的旧 pin 结果作为通过。passed/degraded/failed/review_required 如实区分，所有 manufacturing_approved=false。

## 待实机确认与范围

- Linux 仅做假 COM、纯分析、真实临时文件/SQLite/源码包检查；本批未跑 Windows/SolidWorks、人工目视或全面回归。
- 本批是新建实体零件的有界事务，不声称已自动改造全部旧建模入口或旧钣金入口。已有滚筒与出图改型沿用先前独立检查点路径。
- 草图圆/闭合线段轮廓获准；弧线复杂轮廓只承认待支持，禁止用估算造型冒充原生体验收。
- 观测提供与出图一致的 hash/原子证据/reviewing 边界，尚无新的建模目视签收 UI；不自动生成 accepted。
- `STEAL_NOTES.md` 外部原文件仍未定位。本批按用户贴出的八点实现，没有宣称读过其 §6，也未复制第三方实现。
- 出图 D4 全六格、D2/D3/D5 目视、D6 和旧 pin p248 固定面板仍按原问题跟进，本批不销项。

接口签名核对依据（2025 官方 API，仍待当前安装版本实测）：

- [FeatureRevolve2](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~FeatureRevolve2.html)：20 个参数、草图 mark 0、轴 mark 4/16。
- [Copy2](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBody2~Copy2.html)：显式 PreserveFaceIDs。
- [ClosestDistance](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~ClosestDistance.html)：真实 solid bodies、米、-1 表示无解，验证两端坐标一致。
- [Operations2](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBody2~Operations2.html)：消耗临时体、NULL/S_FALSE 不当作零。
- [swBodyOperationType_e](https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBodyOperationType_e.html)：SWBODYINTERSECT=15901。
- [IFaultEntity](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFaultEntity_members.html)：Check3 的 Count，未确认有效体时拒绝 Boolean。
