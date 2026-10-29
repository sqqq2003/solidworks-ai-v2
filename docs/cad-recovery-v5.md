# CAD 写入恢复、请求回执与未决隔离

本轮复用现有 Pack-and-Go、`SessionLease`、跨进程 OS 写锁、滚筒改型执行器和审核工作区。首个实际接入点是已有滚筒/映射尺寸改型，未增加新的建模框架。原程序和用户原始 CAD 保持原位；恢复目标是本次独立工作区里的隔离副本。

## 已落地接口

| 接口 | 行为 |
| --- | --- |
| `cad_checkpoint.create_checkpoint(files, directory, scope=..., snapshot=..., originals=...)` | 复制已关闭的隔离 CAD，逐个记录源/备份 SHA256、JSON 特征/体快照、只读原件哈希，落盘 manifest |
| `cad_checkpoint.restore_checkpoint(checkpoint, adapter)` | 核对 manifest 和备份，调用 adapter 检查 ActiveDoc/归属并关闭，确认完整文件集已卸载，逐文件替换字节，重开核对快照和 SHA256 |
| `cad_checkpoint.remove_checkpoint(checkpoint)` | 仅删除指定、完整且属于本程序的 checkpoint；有未列入 manifest 的文件时全部保留；不扫描 CAD 目录 |
| `cad_receipts.ReceiptStore.begin/finish/get/unresolved` | SQLite 原子准入、请求状态、缓存结果和事件记录 |
| `ReceiptStore.assert_writer/quarantine/returned` | 每次写入检查 owner 与 RUNNING；未知、回滚未确认、晚返回均保持隔离 |
| `cad_reconcile.reconcile_native(key)` | Windows 上只读探测旧控制程序和旧 CAD 进程身份，确认退出及基线字节后收尾为 FAILED，不重放请求 |
| `roller_variant.native.run_native(..., state_db=None, idempotency_key=None)` | 自动套用 checkpoint 和持久回执；既有调用参数仍有效 |
| `work/verify_roller_rollback.py` | 在审核后的独立工作区，显式注入首次尺寸保存后的失败，校验还原和回执 |

## 正常与失败执行

1. 请求、真实模型哈希和既有映射先通过校验；SQLite 取得 RUNNING 请求身份。
2. 复用现有跨进程写锁、STA 和 owned 新实例证明，保持与用户已打开实例共存。
3. 原件只读 Pack-and-Go，采集映射值、特征、实体边界及装配静态状态。关闭文件后复制整个隔离依赖文件集，并验证备份 SHA256。备份未完整封存不得改尺寸。
4. 每个写操作检查当前 `SessionLease` 和回执 owner。成功仍使用原有保存、重开、尺寸、接口和轴向边界验证；COM 回执不等于制造验收。
5. 尺寸写入后的普通失败触发恢复。如果 ActiveDoc 存在，只接受路径、已登记标题和已登记 COM 包装对象均匹配的隔离目标。不同/未知 ActiveDoc 不会被关闭。必须确认应用无已加载文件，才覆盖隔离文件字节。
6. 恢复后重开，核对特征/体/尺寸/静态快照，关闭后再验 SHA256。全部成功才记录 RESTORED；任一步失败为 ROLLBACK_UNCONFIRMED，保留所有现场。

checkpoint 保留在 `<native-output>/rollback-checkpoint/`，包含 `manifest.json`、编号备份、成功恢复时的 `rollback.json`。`checkpoint.json` 继续是既有执行日志，不冒充 CAD 字节备份。

## 幂等与隔离

默认 key 是规范化 document、原件及映射文档 SHA256 聚合 revision、规范化 payload SHA256 的组合哈希。需要与上游请求 ID 对接时可传 `idempotency_key`；同一显式 key 绑定的 document/revision/payload 不同，返回 `IDEMPOTENCY_CONFLICT`。

同 key 的 COMPLETED 或已收尾 FAILED 只返回原结果，`replayed=true`、`readback_repeated=false`，不另建输出、不再次启动 SolidWorks。FAILED 不自动重试。新请求需重新核对模型/参数并审核，旧工作区的永久 execution claim 仍保留。

回执状态为 RUNNING / COMPLETED / FAILED；独立 `session_state` 管理 RUNNING、RECOVERING、OUTCOME_UNKNOWN、RETURNED_LATE、ROLLBACK_UNCONFIRMED 和 RESOLVED。前五种均拦截新的引擎写请求，包括换目录、换 document 的请求。晚返回不能把未知执行自动改成成功。

默认库为 `%LOCALAPPDATA%/SolidWorksAI/control-v1.sqlite3`。常规入口应使用同一默认库；`--state-db` 为受控集成/隔离测试接口，不能通过换库绕过未决现场。已使用 `run_on_task_sta` / `require_model_write` 的旧写路径也会检查默认库未决状态。旧路径尚不具备滚筒新增的自动 checkpoint/请求生命周期，未受上述 session 边界约束的外部脚本也不在保证范围内。

本次受控 lease 的超时、显式退出和终止路径都禁止 kill/ExitApp。超时只停止等待并阻断后续写入，原 OS 写锁继续由 STA 持有至返回；进程崩溃后即使 OS 锁释放，SQLite 未决记录仍阻断新写。

## 调用示例

正常审核工作区仍走原有接口：

```powershell
python work/delivery.py prepare request.json --out C:\SW-AI-Test\review-1
python work/delivery.py status C:\SW-AI-Test\review-1
python work/delivery.py approve C:\SW-AI-Test\review-1 --reviewer "Mechanical reviewer" --review-sha256 <review_sha256>
python work/delivery.py execute C:\SW-AI-Test\review-1 --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --approval-sha256 <approval_sha256>
python work/delivery.py receipts --key <request_key>
```

**改一半还原**的实机测试必须使用另外准备、审核的新工作区；执行后该工作区不能用于正常执行：

```powershell
python work/verify_roller_rollback.py C:\SW-AI-Test\fault-review --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe" --approval-sha256 <approval_sha256> --enable-fault-injection
```

这是明确的故障测试，会在首个改动实际 Save3 并关闭后抛错。检查 `execution.json`、`rollback-fault-test.json`、`native-output/rollback-checkpoint/manifest.json`、`rollback.json`、SQLite 回执及原件前后哈希。返回码 3 表示需要独立复核；不是失败重试指令。

崩溃/超时后的 reconcile：先保留现场，由操作者确认旧控制程序与旧任务 SolidWorks 已安全退出，再从新的 Python 进程执行：

```powershell
python work/delivery.py reconcile --key <request_key>
```

程序自己不杀进程。使用 PID + Windows 创建时间区分原进程和复用 PID；无权限探测、身份未记录、旧进程仍活着、checkpoint 未封存或未恢复基线时均拒绝解除隔离。必须先人工处理具体现场，再重新核对。reconcile 只证明进程已退出和文件基线一致，明确 `native_reopen_verified=false`，不授予工程验收。运行中 PID 仍活着时，本版没有强制接管/解锁按钮。

## Gork 统一实机验收

在独立目录 checkout 本 PR 的**代码 pin**；保留原安装、原 CAD、旧候选包。新版候选矩阵增加三项 native 检查：

| 检查 ID | 必须带回的证据 |
| --- | --- |
| `checkpoint_half_edit_restore` | 审核记录、故障发生在首个实际保存之后、manifest 及备份 SHA256、原件/副本前后哈希、重开特征/实体/尺寸快照、rollback-fault-test.json；另测外来 ActiveDoc/关闭失败/备份篡改不能恢复 |
| `request_idempotency_and_conflict` | 同 key 完成后重发不启动新实例、不新增副本；同 key 改 payload 报冲突；两进程同库竞争仅一个写者；原 CAD 不变 |
| `unresolved_session_reconciliation` | 超时、晚返回、控制程序崩溃、回滚不确认分别阻断后续写入；CloseDoc-only 不 kill/ExitApp；旧进程存活/探测失败不能解锁；恢复字节且旧进程退出后才 reconcile 为 FAILED/RESOLVED |

源文件包可在独立、干净 checkout 内使用既有 `python work/delivery.py candidate --root . --revision <code-pin> --out <new-candidate-directory>` 生成，包含矩阵和回传模板。不要沿用旧 pin 的实机结论。

本轮只跑上述边界及受影响的滚筒、session、工作区、候选包与证据审计模拟检查，没有进行全面回归或 SolidWorks 实机测试。Windows COM 包装对象身份、Pack-and-Go 引用装载、配置快照、原生实体和重开行为均需 Gork 实机确认。checkpoint 工具与回执接口可供孔距等后续执行器复用；本 PR 没有把所有其它建模执行器自动改造成可恢复事务。
