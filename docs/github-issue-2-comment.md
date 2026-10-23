# Issue #2 评论

不要用这段文字关闭 issue。#2 仍打开。配合、干涉、运动和 Pack and Go 都还没做。状态是 `sw_live_envelope_verified`，不是全面改型完成。

---

GORK-A01-005：包络方程已在用户电脑核实，证据在 `dev/cloud-ai`（PR #1）。只有文档和 JSON，没有客户 CAD。

- 状态 `sw_live_envelope_verified`。母体 GT-ZX-1300（不是 QL-5050），磁盘基准 Length/Width/Height/FootHeight = 1300/600/750/50，原工程未覆盖。SW Premium 2025 SP1.2 / Rev 33.1.2。
- 工作副本 `C:\Users\yue\A01-live-work\A01-1800x900x1500-v2.SLDASM`。EquationMgr.Value 读回 Length=1800 Width=900 Height=1500，envelope_match=true。
- 方程写入：Equation PROPERTYPUT 在这台 SW2025 上是 no-op。有效做法是 Delete(index) 后 Add2(same_index, equation, solve=False)。Delete 后 Add(-1) 会丢变量。本机 `D:\工程\改机工具\apply_variant.py` 的补丁没有合进本仓库。
- 未宣称：配合 / 干涉 / 运动、DeckHeight 与 RollerLong 的 Value()（读回 -50 / 100，方程文本正确）、Pack and Go、10 个 pending_mapping。
- Linux 云端测试仍是 `sw_live=not_applicable_on_linux`，不是这次实机结论。

证据：`docs/a01-windows-live.md`，`results/windows/live_reshape_verified.json`。
