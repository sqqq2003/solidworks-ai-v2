# PR #65 — CAD 恢复与未决隔离测试交接

- PR：https://github.com/sqqq2003/solidworks-ai-v2/pull/65
- 代码 pin：`7524bc2e77d11fc089c529ffb3f03c6db5b9d949`
- 代码 tree：`c38ad1a55722ef93398c2647eb30bf037bda416c`
- 基于 PR #64，独立增量分支 `feat/cad-checkpoint-receipts-v5`，未合并。
- [完整源码测试包](gork-test-kit.zip)：526 个源码文件，含 source.zip、candidate.json、matrix.json、submission-template.json、source-index.json、READ-FIRST.txt。
- ZIP SHA256：`3b58b28ccef08f865dcb1c5af61eaab19c0a50b7b9e51d79842de58abfff3ba7`，大小 1,241,150 bytes。
- 内层 source.zip SHA256：`a42799240abdfffb6048e8a1a29d53b9118c7c0cf0ee5b7bc8ba548958296d03`。

后续交接附件提交不是新的源码版本。回传模板、原生证据及修复任务必须使用上面的代码 pin，不能用仅增加附件的 PR HEAD 替换。

## 主要交付

1. 滚筒映射尺寸执行前封存隔离 CAD 的 checkpoint、源/备份 SHA256、特征/体/尺寸快照；失败后 CloseDoc、恢复副本字节、重开及再次核对，失败标记 ROLLBACK_UNCONFIRMED。
2. SQLite 幂等请求回执、冲突检测、已完成/失败请求缓存，禁止 RUNNING 请求盲目重放。
3. 复用既有跨进程 OS 写锁和 SessionLease，增加持久未决隔离、owner 写检查、晚返回保护、Windows 进程创建时间核对及保守 reconcile。
4. `work/verify_roller_rollback.py` 在已审核独立工作区内，首个实际 Save3 后主动报错，核对恢复结果；必须显式 `--enable-fault-injection`。

详细接口、调用步骤、限制和实机清单见 [docs/cad-recovery-v5.md](../../docs/cad-recovery-v5.md)。自动回滚首先接入滚筒执行器；孔距等其它执行器可复用公共接口，尚未全部接入。

## 验证与实机分配

`validation.json` / `targeted-tests.log`：149 项针对性检查，148 通过、1 项历史原件基线缺失跳过。使用真实临时文件、SQLite 和子进程竞争，CAD/进程归属证据为 fake。没有全面回归、桌面或 Windows/SolidWorks 实机测试。

`package-verification.json`：已校验本次 ZIP 的 SHA256、pin、矩阵、文件清单，并安装到新的云端目录后核对。没有执行安装后源码、安装运行时或启动 SolidWorks；不构成工程验收。

Gork 本轮增加三项 native 检查：`checkpoint_half_edit_restore`、`request_idempotency_and_conflict`、`unresolved_session_reconciliation`。同一模板保留此前十项覆盖；新 pin 未重测的项目应保持 review_required，不继承旧 pin 的 passed。

保留原安装、原 CAD 和旧候选包。仅在独立新目录测试。程序不 kill/ExitApp；未知 ActiveDoc、关闭失败、备份异常、未封存或原进程仍存活时不得强制解除隔离。reconcile 不自动重放、不授予制造批准。
