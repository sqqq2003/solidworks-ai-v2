# 交 Gork 复测包 v11：拆分后的钣金/滚筒生成与参数公式报错

- **源码 pin：`74808b59de97e4aa74200ade67569d730738f30e`**；代码 tree：`330dde7cf3cd069739666df3387dea7af821dd78`。
- 这个 pin 是 #73（拆分 `solidworks_generator.py`）的分支再合并 #74（参数公式报错）后的提交，两者都基于 #72（把 dev/cloud-ai 合进函数参数建模分支）。三个 PR 都还没有合并。
- [完整源码测试包](gork-test-kit.zip)：603 个源码/受控合成夹具文件，1,467,007 bytes。
- **测试包 ZIP SHA256：`d48befb35332c5b58e487f1349cfffb81aab180346cf1cbf83a142292313f368`**。
- 内层 source.zip SHA256：`d17d9058c51f0a54efbd1676671c7f4dd88e6b4d3d38ab8ba5d834256356d463`；candidate_id：`d8f98c3a2aeaa898e004c12279acf1cd405c0578e9572471776842ae40f35d5c`。

本目录只添加交接材料，不改源码 pin。**本次没有在 Windows 上运行，也没有启动 SolidWorks**；所有结论都是云端离线结果，`manufacturing_approved=false`。

## 这次改了什么

1. **#72**：把 dev/cloud-ai 的最新改动合并到函数参数建模分支，作为后面两个改动的基线（`88cfc40`）。
2. **#73**：把 `src/solidworks_generator.py` 里不需要 COM 的几何计算搬到两个新文件：滚筒部分在 `src/roller_geometry.py`，钣金部分在 `src/sheet_metal_geometry.py`。`solidworks_generator.py` 继续重新导出这些名字，旧的 import 写法不用改。真正调用 SolidWorks 的代码没有改逻辑，但文件被大幅改动，所以钣金和滚筒的实机生成需要重新确认。
3. **#74**：参数公式写错时（语法错误、白名单外的函数、规则结构不对）统一抛 `ValueError`，命令行和界面显示一句能看懂的错误，而不是 Python 内部异常。

和基线 `88cfc40` 相比：12 个文件内容有变化，新增 2 个文件，没有删除文件，其余 818 个文件 blob 不变。

## 云端已做的验证

- `package-verification.json`：`work/delivery.py inspect-kit` 通过；`install` 写入全新目录 605 个文件（退出码 3 是预期的 `source_installed_runtime_required` 阶段）；安装目录里 `work/verify_test_handoff.py .` 结果 `verified`，0 个不一致。
- `validation.json` 与 `installed-tests.log`：在安装出来的新目录、新虚拟环境（只装 `requirements-cloud.txt`）里运行 `xvfb-run -a python work/run_cloud_tests.py`，Python 3.11.18：**1232 项运行，1228 通过，0 失败，0 错误，4 跳过**。跳过原因都是云端缺少真实 DWG 或 LibreDWG，与本次改动无关。仓库里用 Python 3.12 和 3.11 跑结果相同。
- 拆分前后 `examples/sheet_metal_dry_run.py` 的输出在去掉哈希和时间戳后完全一致。
- 离线公式检查：两个示例公式都能算出结果；故意写错的公式返回 `{"status": "failed", "error": "invalid expression syntax"}`，白名单外函数返回 `"function outside numeric whitelist"`，退出码都是 1。

这些都是模拟和离线结果，不能代替 SolidWorks 实机验收。

## Gork 请先复测这些

准备工作：把 `gork-test-kit.zip` 解压到**新的空目录**（例如 C 盘新文件夹），建新的 Python 虚拟环境，按包里 `READ-FIRST.txt` 先运行 `py work\verify_test_handoff.py .`。不要覆盖 D 盘上的现有程序（包括 `D:\工程\钣金导入\程序`），不要杀进程或重启已在运行的 SolidWorks，所有输出写到新的独立目录。下面的 `$sw` 指本机 `SLDWORKS.exe` 的完整路径，例如 `"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe"`。

### (a) 钣金：对应矩阵项 `sheet_rebuild_flat_pattern`

按 [docs/p0-sheet-metal.md](../../docs/p0-sheet-metal.md) 的“正式独占进程入口与 p248 重试日志”一节操作：

```
py work\probe_owned_solidworks.py --sw-exe $sw --out <新目录>\owned-session.json
py src\sw_tool_cli.py --mode sheet --input <独立工作副本.dwg> --out <新目录>\p248.SLDPRT --profile 248 --thickness 2.5 --radius 1 --angle 90 --sw-exe $sw
py src\sw_tool_cli.py --mode sheet --input <独立工作副本.dwg> --out <新目录A>\p209-k025.SLDPRT --profile 209 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.25 --sw-exe $sw
py src\sw_tool_cli.py --mode sheet --input <独立工作副本.dwg> --out <新目录B>\p209-k050.SLDPRT --profile 209 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.5 --sw-exe $sw
```

这里的 t=2.5、R=1、90 度、K 值只是本次复测的输入，不是默认值。p248 请记录 `Fixed panel pinned for all bend groups`、每轮 `bend_attempts`、实际完成折弯数、重建、关闭保存重开和展开结果。K 对照请记录 `requested_k_factor`、`k_factor_readback`、`bend_allowance_verified`。

如果要跑完整的“生成→重开→测量→展开→DXF”管线，可以用：

```
py work\run_sheet_metal.py <独立工作副本.dxf> --profile 247 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.4 --direction normal --confirm-bends --sw-exe $sw --out <新目录>\sheet-live --live
```

注意 `work\run_sheet_metal.py` 的 `--profile` 从 0 开始数，所以 p248 要写 247；`sw_tool_cli.py` 从 1 开始数。

### (b) 滚筒：对应矩阵项 `roller_800_interfaces`

```
py src\sw_tool_cli.py --mode roller --input <滚筒图纸工作副本> --variant 0 --plan-only
py src\sw_tool_cli.py --mode roller --input <滚筒图纸工作副本> --out <新目录>\roller-v0.SLDPRT --variant 0 --verify-reopen --sw-exe $sw
```

`--variant` 从 0 开始，请至少跑一个规格，最好再跑一个不同规格。记录生成是否成功、重开后的尺寸核对结果，以及两端接口尺寸是否和图纸一致。

### (c) 参数公式（离线即可）：对应矩阵项 `parametric_function_units_and_dependencies`

```
py work\parametric.py preview examples\function-block.json --length 80 --width 30 --height 10 --out <新目录>\block-preview.json
py work\parametric.py materialize <新目录>\block-preview.json --out <新目录>\block-features.json
py work\parametric.py preview examples\function-roller.json --length 800 --width 1 --height 1 --out <新目录>\roller-preview.json
```

然后复制一份 `function-block.json`，把某个 `expression` 改成写错的公式（例如 `length * (width` 或 `__import__("os")`），再 preview 一次，确认输出是一句可读的错误（`status: failed`），没有 Python traceback。也可以在 `python app.py` →“参数化建模”→“编辑函数”里做同样的检查。

**已有的参数审核工作目录需要重新 prepare。** 因为代码哈希变了，之前用旧代码生成的 review/approval 工作目录不能直接拿来 apply，请用本包重新走一遍 preview → prepare → approve。

### 回归

再跑一次 `py work\run_cloud_tests.py`，报告矩阵项 `cloud_regression`。

## 回传要求

固定本源码 pin，填写 `submission-template.json`：Windows/Python/SolidWorks 版本、SolidWorks 进程 PID、真实退出码、阶段 JSON、日志、截图及其 SHA256。每项按 passed / degraded / failed / review_required 分类。需要实机或人工目视的项目不能用离线结果填通过。本批优先回报四项：`sheet_rebuild_flat_pattern`、`roller_800_interfaces`、`parametric_function_units_and_dependencies`、`cloud_regression`；其它矩阵项不要求本次重测。客户 CAD 和模板留在本机，不要上传。
