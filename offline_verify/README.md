# 离线验证、回归和未来 Windows 实机测试包（Issue #25 扩展模块 ⑥）

离线模块，纯 Python 标准库，不依赖 SolidWorks，不改被测代码。
只读检出、只写调用方指定的 out-dir。

## 调用

```bash
# 离线验证：跑已注册套件，写 report.json + report.md
python -m offline_verify.cli verify --root . --out-dir out

# 只跑指定套件
python -m offline_verify.cli verify --root . --out-dir out \
    --only bridge-wiring,pipeline

# 缺失套件不影响退出码（仅当在场套件全过且基线一致时返回 0）
python -m offline_verify.cli verify --root . --out-dir out --allow-missing

# 只生成未来 Windows 实机测试包文档（不跑任何测试）
python -m offline_verify.cli windows-pack --out-dir out
```

退出码（verify）：0 = 全部在场套件通过、基线一致、无缺失套件
（或 --allow-missing 且在场套件全过、基线一致）；1 = 有套件失败/
出错、基线差异，或有缺失套件（未加 --allow-missing）；2 = 输入
错误（检出根不存在、基线文件非法、套件 id 未知）。

运行约定：module 套件运行时，运行器把 `<root>/src` 前置进
PYTHONPATH——仓库测试惯例如此（多数测试文件自设 sys.path 到
src/，个别文件如 test_recovery_review_guards.py 不设、假设 src/
已在路径上）；运行器不改任何测试文件。

## 报告字段说明

`report.json`（格式串 `offline-verify-report/1`）：

- `suites[]`：每套件一条——id、title、status（pass / fail / error /
  missing）、ran / passed / failed / errored / skipped、failures（失败
  用例名清单）、baseline（verdict：match / diff / missing /
  no-baseline；diff 时含 expected 与 delta）、source_pr /
  source_commit、relpath。
- `missing[]`：检出中不存在的套件 id（分支未合并为预期状态，
  绝不计入通过）。
- `unregistered[]`：检出中存在但未注册的 test_*.py 文件（只列出、
  不运行、不计入）。
- `summary`：套件与用例的汇总计数；`complete` 仅当无缺失、无失败、
  无基线差异时为 true。
- `exit_code` / `exit_reasons`：退出码与原因。
- `principles`：固定声明——合并 ≠ 验证通过；mock/离线通过绝不
  是实机通过；缺失套件绝不是通过。

`report.md` 与 `report.json` 字段一一对应，只做展示，不改数字。

## 与各批的关系（收拢了什么）

- 套件注册表（`suites.py`）与基线（`baseline.json`）：#26（桥接契约
  17 项）、#31（接线 8 项）、#32（build/reopen 15 项，Draft 未合并）、
  #23（pipeline 14 项、checkpoint 14 项）、#29（去默认值 5 项、
  bend_allowance 6 项、p0_gork 10 项）、#30（守卫 7 项）、#35（DXF
  14 项，Draft 未合并）、#36（特征树 14 项，Draft 未合并）、#37
  （依赖引擎 17 项，Draft 未合并）、本批自测 12 项。
- 基线更新纪律：基线只能随对应模块的 PR 一起改；改计数必须在
  该模块的 PR 描述中写明新实测数与原因；任何人不得手改数字凑通过。
- Windows 包（`windows_pack.py` → WINDOWS_ACCEPTANCE_PACK.md）：
  A1–A8（#26）、B1–B5（#27/#31）、B6–B10（#32）、D1–D5（模块 ③）、
  C1–C5（模块 ④）、G1–G4（模块 ⑤）、W1–W10（#23/#29/#30 与桥接编译）。
  各批原矩阵的编号与措辞被原样收拢，不另造一套对不上的号；
  W2（p248 全流程）只引用 A2，不重复执行。

## 未实现项

- 本包不跑 tests/ 全部文件，只跑注册表里的套件；未注册文件只
  列出、不运行（见报告 `unregistered`）。
- 本包不做 Windows 实机执行：WINDOWS_ACCEPTANCE_PACK.md 只是
  待 Gork 执行的文档，全部项标 pending_windows_validation。
- 本包不解决各模块分支的合并顺序：#32/#33/#34/#35/#36/#37
  合并前，dev 上的示例报告里对应套件均为 missing，这是预期状态，
  不是本包的缺陷。

## 已知残留（本批不碰，属后续批次）

- dev 上 `src/solidworks_generator.py` 头部仍有一行
  `DEFAULT_BEND_K_FACTOR = 0.44`（#29 删的是 BendAllowanceSpec 的
  默认值，这处生成器常量还在）。本包不引用它、不依赖它；
  自测里有断言保证本包执行路径不给任何默认值常量赋值。
  统一它属于后续批次（见 W10）。

## 回滚方案

本包是纯新增目录（offline_verify/），不改任何现有文件。回滚 =
删除该目录 + 关闭对应 Draft PR；报告只在调用方 out-dir 里，
删 out-dir 即清干净。
