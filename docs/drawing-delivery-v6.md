# 出图技术结果、目视验收与恢复

本轮继续现有三视图、六格比例、BOM、PDF 和 A01 映射尺寸出图线。目标是可核对的交付状态与失败恢复，布局算法及通用造型 DSL 不变。

## 交付状态

| 状态/字段 | 含义 |
| --- | --- |
| `generating` | 尚未收齐图纸、必需 PDF、视图/注解重开读回；不能目视接受 |
| `reviewing` | 等待署名目视决策；SaveAs、离线通过、`pass_pending_visual` 都不等于 accepted |
| `accepted` | 人工对这一份证据及其文件哈希确认了四项目视检查 |
| `rejected` | 人工退回，原因写入独立、不可覆盖的决策记录 |
| `failed` | 原生出图/注解/PDF 阶段失败，保留本页完整失败 JSON |
| `delivery_accepted` | 只有完整技术证据、已收尾请求、当前文件哈希一致且已 accepted 的完整模型图纸才为 true |

`accepted` 是图纸目视版式验收，仍不授予整机工程/制造批准。缺件试图可以 `visual_accepted=true`，但始终 `delivery_accepted=false`、`manufacturing_approved=false`。更改图纸、PDF、对应模型或证据后，旧接受记录失效；读取时重新验哈希，不继承旧决定。

试图窗口新增署名、视图/尺寸注解/比例/图框标题及 BOM 四项勾选、接受与退回按钮。生成按钮不自动勾选、不自动写 accepted。旧结果缺少新证据时保持待审核。批量六格使用下列 CLI 逐张审核；界面按钮处理当前单张试图。

## 逐张原子证据

每次 `ManufacturingDriver.export_manufacturing` 先生成 `drawing-index.json`，列出本批所有预期页面。每页写入 `evidence/drawing-0001.json` 等，使用同目录独占临时文件、flush、fsync、原子替换；决策使用原子独占发布，两个审核者不能互相覆盖。中断时只能看到上一份完整 JSON，不能用半截报告闯过目视门。

证据包括：输入模型 SHA256、关键实现文件 SHA256、请求比例、保存重开后的视图名称/位置/边界/比例、尺寸/注解/BOM 的原生名称/类型/位置、注释文字、BOM 读回、PDF 解析结果、产物 SHA256、是否遇到 MEMBERNOTFOUND 及事件清单。兼容层成功回退后仍记录发生过的 MEMBERNOTFOUND，不据此掩盖最终未完成的读回。

插入的注解在重开后按原生名称核对类型、位置和注释文字；仅插入数量相同不算完成。A01 必需 PDF 未生成/解析或 PDF 失败时，本页不能进入完整技术状态。前几页成功、后页失败时，已落盘页证据保留；缺页、失败页、未知请求均阻止整批接受。

原始证据保存在本机，包含实际工作路径。用于 GitHub 回传的 `export` 命令另生成仅含代码 pin、页证据哈希、产物哈希、审核人、检查项及状态的 JSON，不包含本机绝对路径或 CAD 二进制。

## 调用接口与命令

公共接口在 `src/drawing_review.py`：`DrawingEvidence`、`inspect_drawing`、`review_drawing`、`inspect_drawing_batch`、`export_visual_review`、`atomic_json`。均不启动 CAD。

```powershell
python work/drawing_review.py inspect C:\SW-Test\drawings\evidence\drawing-0001.json
python work/drawing_review.py batch C:\SW-Test\run
```

打开实际 SLDDRW/PDF 目视检查。复制 `examples/drawing-visual-checklist.json`，逐项确认后将对应值改为 true。未确认项目保留 false。以 inspect 返回的当前 evidence_sha256 记录决策：

```powershell
python work/drawing_review.py review C:\SW-Test\drawings\evidence\drawing-0001.json --reviewer "审核人" --evidence-sha256 <当前哈希> --decision accepted --checklist C:\SW-Test\checks.json --notes "已核对视图、注解、比例、图框及 BOM"
python work/drawing_review.py review C:\SW-Test\other\evidence\drawing-0001.json --reviewer "审核人" --evidence-sha256 <当前哈希> --decision rejected --checklist C:\SW-Test\checks.json --notes "退回原因"
python work/drawing_review.py export C:\SW-Test\run --revision <code-pin> --out C:\SW-Test\visual-acceptance.json
```

accepted 决策不能覆盖；修改图纸后需新证据并重新审核。CLI 退出 0 仅表示本次查询/审核范围内可交付图纸已 accepted；待审核和缺件试图退出 3，失败/退回退出 1。工程制造批准始终独立。

## 接到真实尺寸修改入口的 checkpoint

`A01ProductionDriver.edit_transaction` 复用 v5 的 SHA256 checkpoint。Pack-and-Go 后、首个尺寸写入前，备份整个隔离文件集并采集特征、实体和映射尺寸快照。外层覆盖尺寸修改、配合/检查、图纸及 PDF；任何后续失败都尝试恢复。直接调用 `apply_mapped_dimensions` 也有外套，已处于外层事务时不重复备份。

恢复先确认 ActiveDoc 是本次追踪的 owned 模型/图纸；使用保留句柄或 COM IUnknown 身份验证，不能按前台标题随意接管。只关闭本次追踪且 lease 仍登记的文档，再确认文件全部卸载，恢复副本字节、重开核对快照及 SHA256。不改变用户原件，不删失败产物，不 kill/ExitApp。外来/未知文档、关闭失败、引用仍加载或快照不符时保留现场，进入 ROLLBACK_UNCONFIRMED。

本轮外套接入的是 A01 映射尺寸出图入口。只读缺件试图没有模型尺寸写入；其它旧驱动/整机改型入口未在本轮全部改成可恢复事务。

## 出图幂等与未决隔离

`run_production`、`run_trial` 复用 v5 ReceiptStore、STA、OS 跨进程写锁及 reconcile。key 绑定模型 revision、请求、模板 SHA256、出图实现指纹；同一显式 key 改 payload/模板/实现报冲突。COM 重连不重放视图/注解插入，已完成/失败返回原回执。界面一次新按钮操作创建独立逻辑 key；重试同一请求文件保持该 key。

RUNNING、RECOVERING、OUTCOME_UNKNOWN、RETURNED_LATE、ROLLBACK_UNCONFIRMED 均阻断新写。页证据关联该请求，回执未完成或未知时，页的人工接受也被阻止。COM 清理有断连警告时不按普通技术成功收尾。只读试图在 checkpoint 尚未封存前崩溃时仍需人工恢复，不能用“没有修改尺寸”推断安全并强制清记录。

常规调用使用默认共享 SQLite 库。`run_production(..., idempotency_key=...)` 及 `work/run_a01_production.py --idempotency-key ...` 可接上游请求 ID；`state_db` 只供受控集成/测试，不得换库规避未决状态。详见 v5 文档中的 reconcile 边界。

## Gork 实机故障与目视矩阵

请在全新目录使用本轮完整代码 pin，保留原程序、原 CAD 和旧验收 pin。确认原始请求中的真实映射、尺寸范围、特征、配置和文件 SHA256，准备独立试验副本。以下命令显式注入失败，不用于正常交付：

```powershell
python work/verify_drawing_rollback.py request.json --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --out C:\SW-Test\fault-dim --request-key GORK-DIM-001 --fault-after saved_dimension --enable-fault-injection
python work/verify_drawing_rollback.py request.json --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --out C:\SW-Test\fault-pdf --request-key GORK-PDF-001 --fault-after pdf --enable-fault-injection
```

第一项在真实尺寸批改 Save3 后抛错；第二项在真实 PDF 保存并解析后抛错。核对 `drawing-rollback-fault.json`、checkpoint manifest/备份、原件/副本前后 SHA256、重开快照、完整日志和 FAILED/RESOLVED 回执。返回 3 需独立复核；未到故障点、回滚未确认或原件改变都不能算通过。

候选矩阵新增 `drawing_visual_acceptance`、`drawing_atomic_evidence`、`drawing_dimension_rollback`。请实测 D2–D6 / A2–A3 与 1:5、1:10、1:20 现有组合，带回页证据及人工目视决定。原子写中断、缺 PDF/注解、MEMBERNOTFOUND 回退/失败、旧图纸改字节、两次重连插入次数、失败后还原及外来 ActiveDoc 拒绝恢复均要覆盖。

`drawings_bom_manufacturing` 和 `drawing_visual_acceptance` 的 passed 回传必须增加 `visual_acceptance: {path, sha256}`，并把同一 JSON 列入 `artifacts`。该文件由上述 export 生成；代码 pin、署名、四项勾选、页/产物哈希、完整模型交付标志必须一致。缺失、旧 pin、reviewing、缺件试图或不完整决策一律保持 review_required。审计通过仍只表示提交记录一致，不替代独立实机工程验收。

本轮只做受影响的针对性模拟、真实临时文件/SQLite/子进程测试和虚拟桌面控件测试，未做全面回归；没有 Windows/SolidWorks 实机或人工目视通过结论。新增的原生注解枚举、IUnknown 身份、引用关闭和实体快照仍需 Gork 在实际 SW 版本验证。
