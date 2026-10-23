# A01 参数化改型（GORK-A01-004）

云端这条链路只做模拟。它读取 `data/machine_spec.json`，沿用 `a01.py` 的预检，算出派生尺寸，再用假的 SolidWorks 适配器写下一次要改的变量。`sw_live=not_applicable_on_linux`。不要把这次结果写成实机通过。

目标包络默认 **1800 × 900 × 1500 mm**。未确认的实测余量和未映射的真实零件尺寸保持空，不会填 OEM 数。

## 在 Linux / 云端跑

```bash
python -m pip install -r requirements-cloud.txt
python -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run
python examples/a01_1800x900x1500_dry_run.py
```

`--dry-run` 退出码 0 表示计划已经写出，并且 mock 适配器没有改任何 SolidWorks 文件。计划内部的 `status` 仍是 `review_required`，因为实测余量和 `pending_mapping` 还空着。不加 `--dry-run` 时，和 `python a01.py plan` 一样，`review_required` 返回 3。

回归：

```bash
python -m unittest discover -s tests -v
python work/run_cloud_tests.py
```

`tests/pending_features/` 仍不计入通过。

## 计划里有什么

- 机架尺寸链仍由 `a01.make_plan` 计算。余量未确认时，机架长宽和立柱高是空的。
- 输送面长度、净宽是通用规则：随机架内长、内宽，不是滚筒布置实测。
- `pending_mapping` 列出还没有映射到真实 A01 模型的尺寸。清单见 `docs/a01-dependency-graph.md`。
- 采购件、轴承轴颈、齿距齿数、板厚和螺纹只保留，不覆盖。

模拟夹具在 `tests/fixtures/a01_sim_assembly.json`。文件自己标明 `not_measured_from_real_a01`。它只用于测试尺寸链能否在“余量已知”时算通，不能当成实物测量。

## 下一台 Windows 实机（用户电脑 DDD）

不要在 Linux 上跑下面的实机命令。不要把路径指到原来的工程或 `D:\工程`。`--save-as` 必须是另一份工作副本。适配器在独占会话没证明之前会拒绝写入；它不调用 `ExitApp`、`CloseAllDocuments` 或按进程名结束 SolidWorks。

```bat
cd /d <solidworks-ai-v2 克隆目录>
git checkout dev/cloud-ai
py -3.12 -m pip install -r requirements-cloud.txt
py -3.12 -m pip install pywin32
py -3.12 a01.py doctor
py -3.12 -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run
py -3.12 -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --live --assembly <模板或工作副本>.SLDASM --save-as <新目录>\A01-1800x900x1500.SLDASM
```

`--live` 在没有 pywin32 / SolidWorks 的机器上应返回 2，并写明 `sw_live=not_applicable_on_linux`。在 Windows 上它仍会先过 `sw_session.require_model_write`：没有本任务独占会话时不会打开文件、不会 SaveAs。实机通过与否要等这次命令在 DDD 上跑完，并由 Codex 另轨看证据。云端日志不能代替那一步。

装配配合、钣金生成和工程图导出目前只是下一轨骨架：配合检查不求解，钣金只指向已有的 `solidworks_generator.generate_sheet_metal`，绘图不写 DXF/DWG/SLDDRW。

2026-10-23 用户电脑上的一次部分改型记在 `docs/a01-windows-live.md`。那次用的是 `apply_variant.py`，不是上面的 `--live`。它只说明包络改写、SaveAs 和母体恢复；配合、干涉、运动未验收。


## CODEX-A01-005：映射与事务接口

导出待确认映射（所有条目初始 `pending_mapping`，不是实测数据）：

```bash
python -m src.a01_parametric.cli --length 1800 --width 900 --height 1500 --dry-run --mapping-template runtime/a01-mapping.json
```

`src/sw_api/mapping.py` 的 schema v1 每个参数记录 document、configuration、feature、dimension、unit、depends_on、source、allowed_range、component_kind（editable/fixed/purchased）与 status。confirmed 必须提供完整目标、来源和范围。fixed/purchased、未确认项、未解出的参数不写；重复参数或物理目标、非有限值、单位冲突和越界值拒绝执行。映射确认本身不补齐求解器内未知 OEM 数值，12 项未知仍需独立确认。

`transaction.execute(plan, mapping_payload, port, destination)` 执行单写者锁 → preflight → 差异计划 → checkpoint → 受控修改 → rebuild → 全部可写目标读回 → save-as → reopen → 再读回。无差异不再保存。修改后的任一步骤失败均调用 restore；恢复失败明确返回 recovery_required。结果始终保留 review_required、cad_release_approved=false，配合/干涉/运动为 unverified；MechanicalCheckPort 定义后续本机证据接口。

`MockExecutionPort` 是纯内存模拟，输出不是 CAD 产品。Windows 接入使用 `apply_live(..., mapping_payload=..., driver=...)`；内部通过 `sw_session.run_on_task_sta`，WindowsExecutionPort 在每次驱动调用前重新检查 require_model_write。驱动实现 ExecutionPort 的物理操作方法，并在初始化时绑定源模型。要求：

- preflight 核对真实文档/配置/尺寸、源路径、目标路径大小写与文件别名；拒绝覆盖已有目标、源文件、用户脏文档或无归属文档；在任何写入前验证全部目标存在。
- read/write 以映射单位为边界，驱动负责 SW SI 单位转换、配置选择和尺寸标识解析；不得创建猜测的 OEM 全局变量。
- checkpoint/restore 负责工作副本隔离及原状态恢复，包含本次新建输出；不得删除其他会话文件。保存重开必须返回正确工作副本，检查 OpenDoc6 / SaveAs3 / rebuild 的原生错误码和状态。
- 不结束未知 SolidWorks 进程。超时或失去租约后的恢复必须等待本机会话恢复，不在第二个线程继续 COM 写入。

旧的“仅写方程并 SaveAs”路径已禁用。CLI `--live` 暂不接受驱动，Windows 有 COM 时会明确拒绝缺少映射/事务驱动的调用；上面的旧实机 CLI 示例只保留历史上下文，不能用于当前适配器验收。驱动与映射接好后由 Windows 集成入口调用 Python API。

待 Gork：真实模型/配置/特征与尺寸标识、来源与允许范围、固定/采购件分类，以及重建、保存重开读回、失败恢复和机械检查证据。Linux 模拟不代表 Windows 驱动已实现或已通过。
