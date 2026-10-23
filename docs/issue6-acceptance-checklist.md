# Issue #6 离线测试验收清单（约 10 分钟）

结论先行：计划 B 项（把 #6 五模块写成可单测的第一版）已交付。全部证据为**纯 Python / mock 离线**；两个测试提交只在本地，**未 push、未开 PR**；本轮**未运行 COM、未生成 SLDPRT/SLDDRW、未接触客户 CAD**。

- 验收副本：`C:\Users\yue\Documents\Qoder\2026-10-24\b2095eb3\solidworks-ai-v2`
- 分支：`feat/issue6-offline-tests`（基线 `13cc10c`，来自 `origin/feat/issue6-ql5050px-five-modules`）
- 提交：本分支相对基线 `13cc10c` 的全部本地提交用 `git log --oneline 13cc10c..HEAD` 列出（依次为 issue6 套件、文档、原生生成校验顺序、验收清单、P0 重建、P0 守护测试与本清单修订）
- 说明：`D:\Qoder\solidworks-ai-v2` 在本会话不可访问，未做任何改动；提交只存在于上述 C 盘副本。

## 验收步骤

1. 提交与未推送状态（期望：领先 `origin/feat/issue6-ql5050px-five-modules`、工作树干净、没有 push 记录）

   ```bash
   git status --short --branch
   git log --oneline -4
   ```

2. 全量回归（期望 `473 ran / 466 passed / 0 failures / 0 errors / 7 skipped`，`cross_process_lock_passed=true`，`solidworks_live_verified=false`，`pending_feature_cases` 只剩 `test_turned_part.py: 22`）

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

## 夜间第三轮：P0 图纸残留与贴边缺口重建

- `tests/pending_features/` 三个文件原先都因导入引导层级写错（子目录里用 `parents[1]/src`，应为 `parents[2]/src`）在 import 阶段就失败，把"算法缺失"的真实缺口盖住了。已修正层级。
- 按 `src/CHANGELOG.md` 记录的既有语义重建两个上传快照缺失的函数：`_is_drawing_artifact_loop()`（闭环最大边 ≤2 mm 且面积 ≤0.6 mm² 判为标注残留）与 `convert_border_hole_to_notch()`（贴边矩形槽孔转外轮廓缺口，三边直角、≤0.75 mm 细缝先拉到板边、搭边 <80% 保持为孔、口部 clamp 在边端点内）。
- 接线三处：孔列表装配跳过标注残留并写 warning；`apply_rectangular_relief_expansion()` 先转缺口再考虑板内扩槽并删除该孔；`ensure_intersection_reliefs()` 在交汇点距板边 ≤2 mm 时从板边开缺口，找不到可贴直角边才退回板内孔。
- `test_spur_segments.py`（5 项）与 `test_border_relief_notch.py`（9 项）全部通过，已移入 `tests/` 计入回归；pending 由 36 项降为 **22 项**。
- 另加 `tests/test_border_notch_reconstruction.py` 11 项守护测试，钉住重建时自行决定的边界：顺/逆时针外环、口部 clamp、角部孔按“贴合更长的边”落槽、60×60 大贴边开口不转缺口、交汇点距板边 >2 mm 仍走板内孔、负 `grow` 拒绝、标注残留判定的开环/细长/微小圆边界。全量因此为 **473 ran / 466 passed / 0 failures / 0 errors / 7 skipped**。
- 未做：`test_turned_part.py` 22 项需要 `cad_analyzer.DrawingDimension`、`DrawingAnalysis.dimensions`（当前不读 DIMENSION 实体）与 `turned_part._axial_lengths` / `_radius_ladder`。属车件轨道功能开发，本轮不猜测实现，保留 pending。
- **注意**：标注残留跳过接在生成路径的 COM 段里，离线只覆盖判定函数与扩槽/交汇接线，该跳过本身未经 SolidWorks 实机验证。

## 本机未能验证的部分

- 本机只有 Python 3.14.7，`uv python install 3.11/3.12` 无网络响应（超时无输出），因此**没有在 3.11/3.12 上实跑**；CI（Ubuntu，3.11/3.12）才是真正的版本证据。
- CI 只在 push 到 `dev/cloud-ai` 或手动 `workflow_dispatch` 时触发；本分支未 push，所以 CI 尚未跑过。需要有推送权限的人对该分支手动触发一次。

## 验收时不接受的表述

- 不接受"SolidWorks 实机通过""已生成原生钣金/工程图""OEM 映射已确认""p248 已闭环"——本轮没有任何这类证据。
- 所有"通过"仅指离线测试；`solidworks_live_verified=false`、`sw_live=not_applicable_on_linux` 语义未变。
- `tests/pending_features/` 仍有 22 项车件合约未实现，不计通过。

## 回滚

- 未合并：直接丢弃 `feat/issue6-offline-tests`，回到 `13cc10c`。
- 已合并：revert 本分支相对 `13cc10c` 的 5 个提交（`git log --oneline 13cc10c..HEAD`）。
- 未修改客户 CAD、D 盘副本、git config（提交用一次性 `-c` 身份）。
