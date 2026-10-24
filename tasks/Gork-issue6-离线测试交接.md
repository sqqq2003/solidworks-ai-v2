# 给 Gork：Issue #6 离线测试成果交接（QL-5050PX 五模块 + P0 钣金几何）

发件方：Qoder 桌面 Agent（代码侧，与 Cursor 同一轨道）
日期：2026-10-24
分支：`feat/issue6-offline-tests`（基点 `bf67b67`，本地提交数见包内补丁，**未推送**）

注意：你夜间推进到 `bf67b67`（新增 `panel` / `manufacturing` / `drawing_layout` / `batch` / `bom_tree`），
已把本分支 rebase 到新基点上，无冲突。交接包里记了生成时的确切 HEAD。

用户已授权我在本仓库做代码协作者，git 权限是**只在本地提交**：不 push、不开 PR。
所以这批成果只能通过文件交接给你，不能靠远端分支拿到。

## 一、这批东西是什么（以及不是什么）

已完成的是**离线契约层**：

- QL-5050PX 五个模块（`parameters` / `control` / `assembly` / `sheet_metal` / `drawing_bom`）
  加 CLI 与批量示例，共 77 条离线用例；
- P0 钣金几何里两个「文档写了但代码里不存在」的接口按 `src/CHANGELOG.md` 记录的语义重建：
  `_is_drawing_artifact_loop()`（图纸标注残留小三角不切材料）与
  `convert_border_hole_to_notch()`（贴板边的释放槽跨过板边开成缺口），
  连同 11 条边界守卫用例；
- `tests/pending_features/` 里 14 条契约（`test_spur_segments.py` 5 条、
  `test_border_relief_notch.py` 9 条）提升进正式回归——它们以前一直失败，
  真正原因是三个文件的 `sys.path` 引导写成 `parents[1] / "src"`（= `tests/src`），
  不是算法缺失；
- 全量回归：**474 跑 / 467 过 / 0 失败 / 0 错误 / 7 跳过**，
  `pending_feature_cases = {'test_turned_part.py': 22}`。

**不是**实机结果。证据文件里写死的标记请原样保留，不要改写：

```
solidworks_live_verified = false
sw_live = not_applicable_on_linux
cad_executed = false
mechanical_acceptance = unverified
```

`MockExecutionPort` 是模拟端口。任何一条用例通过，都只说明离线契约成立，
**不能报成 SolidWorks 实机通过**。

## 二、请你在 Windows 实机侧做的事（按顺序）

1. **独占会话拒绝条件**：按 `docs/issue6-offline-tests.md` 里的 `--sw-exe` 路径，
   验证 `WindowsExecutionPort` 在用户已有 SolidWorks 文档打开时**拒绝写入**而不是抢会话。
   我在 Linux 上只能用 `mock.patch.object(sys, "platform", "linux")` 走到这个分支，
   那是模拟，不算你的证据。
2. **`sheet_metal.generate_native()` 参数校验顺序**：本批把参数拒绝提到了平台拒绝之前
   （提交 `ebb09e2`），目的是让「输出已存在 / 后缀不是 `.sldprt` / `output_path` 重复传」
   这三条在非 Windows 上也能测。请在实机确认这三条拒绝**先于**任何 SolidWorks 调用发生，
   即拒绝时不应产生任何 COM 副作用。
3. **重建的两个几何接口**：`_is_drawing_artifact_loop()` 的跳过分支挂在 COM 切除路径上，
   离线只能验证判定本身。请用件10 / 件20（954×151，同形状两件）实机跑一遍，
   确认那个 0.5×1.0 mm、面积 0.25 mm² 的标注残留三角被跳过、`FeatureCut3` 不再返回 None，
   且 Φ2 孔（面积 3.14 mm²）不受影响。
4. **贴边缺口**：用带贴边释放槽的件确认缺口三边直角、不斜切，
   且外轮廓没有自交（SolidWorks 不接受与外环相交的内环）。
5. **p248**：仍以 Issue #5 为准，不要拿本批离线结果去关它。

## 三、包内文件

见同目录 `MANIFEST.md`（含每个文件的 SHA-256）。要点：

| 文件 | 用途 |
| --- | --- |
| `00NN-*.patch` | 从 `bf67b67` 起的全部提交，按序 `git am` 可直接落到你的工作副本 |
| `issue6-acceptance-checklist.md` | 用户 7 点验收用的 10 分钟流程，命令与预期输出都写死了 |
| `issue6-offline-tests.md` | 本批开发说明：做了什么、为什么、缺陷清单、回滚方式 |
| `latest.json` / `latest.log` | 云端回归证据（`results/cloud/`），已复现三次一致 |
| `TASK_STATUS.md` 摘录 | `ISSUE6-OFFLINE-001/002`、`P0-QODER-001` 三条任务状态 |

## 四、怎么落盘

本分支目前只在本地（`feat/issue6-offline-tests`）。两条路任选：

**路径 1（推荐，需要用户先推送一次）**：用户把分支推到 GitHub 后，直接取分支：

```bash
git fetch origin feat/issue6-offline-tests
git checkout -b feat/issue6-offline-tests origin/feat/issue6-offline-tests
```

**路径 2（只能拿到离线交接包时）**：用 `handoff/gork-issue6-20261024/` 里的
补丁或 thin bundle（该目录未入库，靠文件传递）：

```bash
# 方式 B：补丁
git checkout -b feat/issue6-offline-tests bf67b67
git am /path/to/handoff/gork-issue6-20261024/*.patch

# 方式 C：thin bundle（需要本地已有 bf67b67）
git bundle verify issue6-offline-tests.bundle
git fetch issue6-offline-tests.bundle     feat/issue6-offline-tests:feat/issue6-offline-tests
```

落盘后请重跑一次回归，核对与 `results/cloud/latest.json` 是否一致：

```bash
python work/run_cloud_tests.py
```

预期：`474 ran / 467 passed / 0 failed / 0 errors / 7 skipped`。
数字不一致时不要改证据文件去凑，把差异报回来。

**不要**覆盖 `D:\Qoder\solidworks-ai-v2` 或任何 D 盘生产程序；不要动客户原始 CAD。

## 五、回传格式

沿用仓库既有约定，写入 `results/grok-coordinator/`：

```json
{
  "task_id": "ISSUE6-OFFLINE-HANDOFF",
  "status": "received",
  "patches_applied": false,
  "regression_on_windows": null,
  "sw_live_verified": false,
  "changed_files": [],
  "evidence_files": [],
  "remaining_issues": []
}
```

`false` / `null` 是未执行初始状态，按实际更新。没有实机证据时，
`sw_live_verified` 不得改成 `true`。

## 六、还没做的（不要当成已完成）

- 我在中文 Windows 上发现并修掉了一个只在本机出现的缺陷：`test_equation_health.py`
  10 项在 cp936 下全部 `UnicodeDecodeError`，`sheet_metal_pipeline` 还会把失败诊断写成 GBK。
  已在读写两侧钉死 utf-8，并加了一条中文备注往返的守卫用例。你在 Windows 上复跑时
  如果又见到默认编码相关失败，先怀疑这类未指定 `encoding=` 的 IO。
- `tests/pending_features/test_turned_part.py` 22 条仍待实现，缺的是
  `cad_analyzer.DrawingDimension`、`DrawingAnalysis.dimensions`、DXF DIMENSION 实体读取、
  `turned_part._axial_lengths` / `_radius_ladder`。清单在 `tests/pending_features/README.md`。
  我没动它，因为车件是另一条执行轨道，猜着写只会污染契约。
- CI（`.github/workflows/cloud-tests.yml`）**没有跑过**：它只由 push 到 `dev/cloud-ai`
  或 `workflow_dispatch` 触发，而本分支按授权不能推送。我只做到版本兼容性静态核对
  （Python 3.11/3.12 语法扫描通过、`ezdxf==1.4.4` 对齐、编码纪律审查）。
  需要由有推送权限的人触发。
