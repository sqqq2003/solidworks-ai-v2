# A01 Windows 实机记录（GORK-A01-005）

状态：**sw_live_envelope_verified**。

这是用户电脑上的包络方程核实，不是全面改型完成。Linux 云端测试不能把它写成 SolidWorks 全面通过。配合、干涉、运动没有单独认证。

SolidWorks Premium 2025 SP1.2 / Rev 33.1.2。

## 母体

- 文件：`GT-ZX-1300x000x750-001x1.SLDASM`
- 路径：`D:\工程\滚筒工程\滚筒\斜\斜滚筒线（120W电机） 标准\斜滚筒线-1300x000x750-方向A\装配图\GT-ZX-1300x000x750-001x1.SLDASM`
- QL-5050 不是这台机器。那是只有 DWG 的封箱机。
- 磁盘基准：Length=1300，Width=600，Height=750，FootHeight=50。原工程未覆盖。
- 只读打开 13 个方程，关闭时没有保存。正文在 `results/windows/readonly_equation_dump.json`。母体上 DeckHeight 的只读 `Value()` 是 700，RollerLong 是 700。这只是只读转储，没有把它们写成求解器里的已解算尺寸。

## 工作副本

`C:\Users\yue\A01-live-work\A01-1800x900x1500-v2.SLDASM`

`EquationMgr.Value` 读回：Length=1800，Width=900，Height=1500，FootHeight=50。`envelope_match=true`。`checks.equations_readback` 为 pass。证据：`results/windows/live_reshape_verified.json`、`results/windows/live_reshape_summary.json`。

这次改写用的是用户电脑上的 `D:\工程\改机工具\apply_variant.py`，不是本仓库的 `--live` 事务驱动。

## 方程写入

在这台 SW2025 上核实：

- `Equation` 的 PROPERTYPUT 不改方程。
- 有效做法：`Delete(index)`，然后 `Add2(same_index, equation, solve=False)`。
- Delete 之后若仍有方程引用该名字，`Add(-1)` 或 `Add3(-1)` 返回 -1，变量丢失。
- 脏会话 Close 且不存盘，可以从磁盘恢复。

本机 `apply_variant.py` 的 `_equation_put` 已有 Delete+Add2 回退。该补丁不在本仓库，也没有合进客户路径。仓库里 `src/sw_api/win32com_backend.py` 的未接入助手只记下同一写法，`apply_live` 不调用它。

## 没有写成 pass 的检查

- 配合、干涉、运动：`not_separately_certified`。
- DeckHeight 方程文本是 `"Height" - "FootHeight"`，工作副本上 `Value()` 和重建后 `Value()` 都是 -50。不当成尺寸已解算。
- RollerLong 方程文本是 `"Width" + "RollerLongExtra"`，工作副本上 `Value()` 是 100。不当成尺寸已解算。
- 工作副本仍引用母体零件。归档需要 Pack and Go。Pack and Go 未做。
- 10 个 pending_mapping 仍 pending：滚筒节距、滚筒数量、传动中心、链节距、链轮齿数、轴承轴颈、电机 X/Z、轴承跨距、螺纹大径。
- 板厚 2.0 只从零件名推断，`production_approved=false`，求解器仍 pending。
- 这次实机 JSON 不是 `src/sw_api/mapping.py` schema v1 的 confirmed 行。confirmed 仍要 document、configuration、feature、dimension、source 和 allowed_range。
- 仓库里没有 SLDASM / SLDPRT。

## 云端

`python work/run_cloud_tests.py` 仍是 Linux 模拟。它的 `sw_live` 保持 `not_applicable_on_linux`。那次模拟通过不是 `sw_live_envelope_verified`。
