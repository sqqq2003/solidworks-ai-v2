# 首个单参数改型验收

目标：在一套真实 QL-5050PX 的独立工作副本上，只改变一个已审批的长度尺寸，记录原生读回、重建、保存重开、配合/干涉/行程和工程图/BOM。工具默认不启动 CAD，不把记录一致等同工程验收。

## 1. Gork 完成旧项目后准备样例

选择一个允许改变的机架长度；新值由用户/工程师指定，不用包络直接覆盖零件尺寸。用 examples/ql5050px_approved_resize.json 作为结构参考，替换为真实只读快照、真实路径/配置/尺寸、审批来源及目标值。保留采购件和其他零件，规则写 keep。不要把合成示例标成 OEM。

在 request 中增加 acceptance：

```json
{
  "acceptance": {
    "source_kind": "oem",
    "mapping_review_source": "实际审核人及记录编号",
    "mate_inventory_review_source": "实际配合/受影响接口清单的审核记录",
    "source_inventory_review_source": "完整源文件引用清单的审核记录",
    "source_files": ["D:/OEM/机器.SLDASM", "D:/OEM/机架.SLDPRT", "D:/OEM/其他被引用零件.SLDPRT"]
  }
}
```

source_files 必须由真实依赖清单填写完整，工具不会从文件名推断完整性。源文件只读、只计算 SHA256，不复制进交接包。一个原生尺寸之外有其他修改、缺审批、需要改配合或 OEM 声明/文件缺失时，首轮预检阻塞。预检通过仅表示单参数受控试跑的输入就绪；不代表整机工程图、其他 OEM 字段或生产放行就绪。

## 2. 生成验收包（在能读取源模型的 Windows 工作区）

```
python work/ql_variant_acceptance.py prepare --request D:/验收/request.json --out D:/验收/case-001
```

输出 case.json 和 evidence-template.json，退出码 0 表示单参数预检就绪，3 表示阻塞。目录必须全新。case.json 绑定请求、驱动计划、唯一目标、源文件校验和及 case_id。修改请求或源模型后重新生成、审核，不手改 case.json。

云端可用合成示例检查阻塞路径：

```
python work/ql_variant_acceptance.py prepare --request examples/ql5050px_approved_resize.json --out runtime/rehearsal-fixture-new
```

此示例应返回 3，不能拿去运行真实 CAD。

## 3. Windows 受控执行与证据

确认 SolidWorks、pywin32 和独占会话机制可用，工作根目录全新，原件备份齐全。Gork 核对 case.json 的 expected、drive_plan 和 source_sha256，确认扫描后源文件未变，再调用现有入口：

```python
import json
from pathlib import Path
from ql5050px.native_machine import run_owned_native
case = json.loads(Path('D:/验收/case-001/case.json').read_text(encoding='utf-8'))
assert case['status'] == 'preflight_ready' and not case['blockers']
# 此处仅示意现有 Windows API 调用；请先完成上述人工核对。
receipt = run_owned_native(
    sw_exe='C:/实际安装目录/SLDWORKS.exe',
    work_root='D:/验收/native-001',
    operation='drive', payload=case['drive_plan'])
Path('D:/验收/case-001/native-receipt.json').write_text(
    json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
```

仓库根目录运行时先配置 src 到 PYTHONPATH，或在脚本中加入 sys.path.insert(0, str(Path.cwd()/'src'))。示例安装路径必须替换。此调用仅执行尺寸修改、读回、重建及保存重开；不会自动完成下表的工程检查和图纸输出。

写入前新增基准读回检查：当前尺寸与审批前值不一致、NaN/Inf、未知单位或缺基准值都会拒绝，不继续写入。失败保留工作副本与日志，不强制关闭未知会话，不覆盖原件。每一步都必须收集原生报告/截图/输出文件：

| step | 验收内容 |
|---|---|
| source_isolation | Pack and Go 引用全部位于本次工作根，源文件不变 |
| dimension_before | 原生修改前尺寸值、配置和尺寸全名 |
| dimension_after_reopen | 保存关闭重开后同一配置、同一尺寸读回新值 |
| rebuild | 零件与总装重建，无未解释错误 |
| save_reopen | 生成 SLDASM/SLDPRT 可关闭重开，引用正确 |
| mates | 对照审批前清单，配合状态及受影响接口无未解决错误 |
| interference | 原生干涉报告逐项核对，不能把空返回直接当通过 |
| travel | 相关机构完整行程及安装空间确认 |
| drawing | 改型工作副本的工程图输出、尺寸关联及人工核对 |
| bom | BOM 数量、编号、材料与工作副本一致 |

图纸/BOM 当前仍需真实模板、材料及尺寸引用；缺项保持 not_run，不删除步骤凑通过。保留未解释失败。回滚只丢弃独立工作副本，源文件若变动立即停止并核查备份。

## 4. 填证据并汇总

复制 evidence-template.json 为 evidence.json，填写 operator、observed_at_utc、source_revision、simulated_only=false 和会话来源。只有确实验证过的步骤才填 passed；其他为 failed 或 not_run。会话 ownership 必须来自 spawned_pid_and_live_handle 证据、attached_existing=false，不能凭空填写。

每一步 artifacts 是相对 evidence.json 所在目录的文件清单，例如 `[{"path":"reports/rebuild.json","sha256":"文件实际SHA256"}]`。尺寸两步额外填写 value_mm、configuration、dimension。可用 PowerShell Get-FileHash -Algorithm SHA256 计算哈希（写入小写）。不提交原始客户 CAD；证据及 CAD 留本地授权目录。

```
python work/ql_variant_acceptance.py audit --case D:/验收/case-001/case.json --evidence D:/验收/case-001/evidence.json --out D:/验收/case-001/report-001.json
```

报告给出通过/失败/未测计数、缺失步骤、错误读回、证据变更、源文件变更和计划编号错配。证据路径必须在证据目录内，已有报告不会覆盖。退出码 0 的 evidence_consistent 只说明提交的记录和文件一致，不独立证明原生真实性；工程师仍需审查运动、干涉、加工与安全，production_release 永远为 false。
