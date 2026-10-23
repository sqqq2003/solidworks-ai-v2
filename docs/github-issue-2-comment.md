# Issue #2 评论草稿

不要用这段文字关闭 issue。#2 仍打开。配合、干涉、运动和 Pack and Go 都还没做。

---

GORK-A01-005 部分实机证据已记在 `dev/cloud-ai`（PR #1），只有文档和 JSON，没有客户 CAD。

- 母体是 `GT-ZX-1300x000x750-001x1.SLDASM`（SW Premium 2025 SP1.2 / 33.1.2），不是 QL-5050PX。只读看到 13 个方程，未保存关闭。
- 用 `D:\工程\改机工具\apply_variant.py` 把 Length/Width/Height/FootHeight 改到 1800/900/1500/50，SaveAs 到 `C:\Users\yue\A01-live-work\A01-1800x900x1500.SLDASM`，母体恢复 1300/600/750，退出码 0。
- 重建对话框由操作者点了「全部忽略」。不把配合、干涉、运动写成已验收。工作副本仍与母体共享零件。
- DeckHeight 只对应 `passline_height` 这个名字。方程正文没有随云端附件到达，所以没有把毫米值写成 confirmed。
- 其余 OEM 尺寸仍 pending。Linux `work/run_cloud_tests.py` 不是这次实机的结论。

证据：`docs/a01-windows-live.md`，`results/windows/`。
