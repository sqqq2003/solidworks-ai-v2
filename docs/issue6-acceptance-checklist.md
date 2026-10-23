# Issue #6 离线测试验收清单（约 10 分钟）

结论先行：计划 B 项（把 #6 五模块写成可单测的第一版）已交付。全部证据为**纯 Python / mock 离线**；两个测试提交只在本地，**未 push、未开 PR**；本轮**未运行 COM、未生成 SLDPRT/SLDDRW、未接触客户 CAD**。

- 验收副本：`C:\Users\yue\Documents\Qoder\2026-10-24\b2095eb3\solidworks-ai-v2`
- 分支：`feat/issue6-offline-tests`（基线 `13cc10c`，来自 `origin/feat/issue6-ql5050px-five-modules`）
- 提交：`3b3013a` 套件与接口修复 → `8244319` 文档 SHA → `ebb09e2` 原生生成校验顺序 → 本次文档提交（`git log -1`）
- 说明：`D:\Qoder\solidworks-ai-v2` 在本会话不可访问，未做任何改动；提交只存在于上述 C 盘副本。

## 验收步骤

1. 提交与未推送状态（期望 `ahead 4`，且除本次文档提交外无其他待提交改动）

   ```bash
   git status --short --branch
   git log --oneline -4
   ```

2. 全量回归（期望 `448 ran / 441 passed / 0 failures / 0 errors / 7 skipped`，`cross_process_lock_passed=true`，`solidworks_live_verified=false`）

   ```bash
   python -X utf8 work/run_cloud_tests.py
   ```

3. QL-5050PX 子集（期望 `Ran 77 tests ... OK (skipped=1)`，跳过项为 `test_refuses_off_windows`）

   ```bash
   python -X utf8 -m unittest discover -s tests -p "test_ql5050px*.py"
   ```

4. 示例入口（期望目录内 4 个产物：`batch.json`、`drawing.json`、`simulation_blank.dxf`、`simulation_bom.csv`）

   ```bash
   python -X utf8 examples/ql5050px_batch.py --output 新目录名
   ```

   `batch.json` 期望：`test_status=offline_simulation_only`、`control.cad_executed=false`、`control.status=pending_mapping`、`pending_mapping` 21 项。

5. 空映射必须是拒绝，不是通过（期望输出 `pending_mapping False 21`，且结果里没有 `simulated_pass`）

   ```bash
   python -X utf8 -c "import sys;sys.path.insert(0,'src');from ql5050px import build_plan;from ql5050px.control import execute_variant;r=execute_variant(build_plan(),{'schema_version':1,'parameters':[]},'work-copy.sldasm');print(r['status'],r['cad_executed'],len(r['pending_mapping']));assert 'simulated_pass' not in r"
   ```

6. 纯净克隆可复现（期望克隆内跑出的 `results/cloud/latest.json` 与仓库提交版本一致）

   ```bash
   git clone --branch feat/issue6-offline-tests <本副本路径> 校验目录
   cd 校验目录 && python -X utf8 work/run_cloud_tests.py
   git diff --no-index results/cloud/latest.json <本副本路径>/results/cloud/latest.json
   ```

   本会话已做过该验证：克隆内 `448/441/0/0/7`，证据文件逐字节一致。

## 夜间第二轮追加

- **纯净克隆复跑**：`ebb09e2` 的干净克隆跑出与提交证据完全一致的结果，说明提交树自身可复现，不依赖本机残留。
- **CI 版本兼容静态检查**：用 `ast.parse(feature_version=(3,11)/(3,12))` 扫描 114 个 `.py`，0 处语法不兼容；`ezdxf` 本机与 `requirements-cloud.txt` 同为 `1.4.4`。
- **`generate_native` 校验顺序**（`ebb09e2`）：参数拒绝（已存在文件、错误后缀、重复 `output_path`）原先排在平台拒绝之后，导致 Linux CI 只能跳过 2 项；现改为先校验参数、再拒绝非 Windows。所有拒绝条件都保留，Windows 上仍为 `448/441/0/0/7`，Linux 上这 2 项会实跑。
- **Linux 分支模拟核验**：在 Windows 进程内把 `sys.platform` 补丁成 `linux` 后确认——合法路径仍抛 `RuntimeError("native sheet generation requires Windows")`，错误后缀与重复 `output_path` 抛 `ValueError`。**这是模拟平台检查，不是 Linux 实机证据。**

## 本机未能验证的部分

- 本机只有 Python 3.14.7，`uv python install 3.11/3.12` 无网络响应（超时无输出），因此**没有在 3.11/3.12 上实跑**；CI（Ubuntu，3.11/3.12）才是真正的版本证据。
- CI 只在 push 到 `dev/cloud-ai` 或手动 `workflow_dispatch` 时触发；本分支未 push，所以 CI 尚未跑过。需要有推送权限的人对该分支手动触发一次。

## 验收时不接受的表述

- 不接受"SolidWorks 实机通过""已生成原生钣金/工程图""OEM 映射已确认""p248 已闭环"——本轮没有任何这类证据。
- 所有"通过"仅指离线测试；`solidworks_live_verified=false`、`sw_live=not_applicable_on_linux` 语义未变。
- `tests/pending_features/` 的 36 项原始特征合约仍未实现，不计通过。

## 回滚

- 未合并：直接丢弃 `feat/issue6-offline-tests`，回到 `13cc10c`。
- 已合并：revert `3b3013a`、`8244319`、`ebb09e2` 三个提交。
- 未修改客户 CAD、D 盘副本、git config（提交用一次性 `-c` 身份）。
