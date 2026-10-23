# A01 Windows 实机记录（GORK-A01-005）

这是用户电脑（DDD）上的一次部分实机记录。Linux 云端测试不能把它写成 SolidWorks 通过。配合、干涉、运动都没有验收。

## 母体

- 文件：`GT-ZX-1300x000x750-001x1.SLDASM`
- 目录：`D:\工程\滚筒工程\...\斜滚筒线-1300x000x750-方向A\装配图\`
- 目录中间段按操作者原文保留省略号，没有补全。
- QL-5050PX 不是这台机器。那是只有 DWG 的封箱机。
- SolidWorks Premium 2025 SP1.2，修订版 33.1.2。
- 只读打开，看到 13 个方程，关闭时没有保存。

13 条方程正文没有随云端附件到达，所以 `results/windows/readonly_equation_dump.json` 只记操作者报告，`equations` 为空。没有凭记忆补方程。

## 这次怎么改的

用的是已有脚本 `D:\工程\改机工具\apply_variant.py`，不是本仓库当前的 `--live` 事务驱动。

目标：Length=1800，Width=900，Height=1500，FootHeight=50。

SaveAs 工作副本：`C:\Users\yue\A01-live-work\A01-1800x900x1500.SLDASM`。

母体随后恢复为 1300 / 600 / 750。进程退出码 0。

重建时弹出 SOLIDWORKS 的“下一步做什么”对话框，操作者点了「全部忽略」。

## 没有验证的部分

- 配合没有检查通过。
- 干涉没有检查通过。
- 运动没有检查通过。
- 没有做 Pack and Go。工作副本仍和母体共享零件。
- DeckHeight 只对上参数名 `passline_height`。毫米值、配置、特征和允许范围都没有进入本仓库，规格里它仍是 pending，映射状态是 unconfirmed，不是 schema 的 confirmed。
- 滚筒节距、数量、链节距、齿数、轴颈、电机坐标、轴承跨距、板厚、螺纹大径仍 pending。
- 仓库里没有 SLDASM / SLDPRT。

## 云端

`python work/run_cloud_tests.py` 仍是 Linux 模拟。它的 `sw_live` 保持 `not_applicable_on_linux`。
