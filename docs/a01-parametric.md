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
