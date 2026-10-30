# PR #68 — 最新测试回传后的整合补丁

- PR：https://github.com/sqqq2003/solidworks-ai-v2/pull/68
- 代码 pin：`d029305b3aa19aa0b41b72a1505c6579d3828921`
- 代码 tree：`929121ed7e4221b8af19e2e9dd5c3989d716cbfe`
- 源码基线：PR #66 的 Windows 兼容更新 `36630fb8ce4540f03ddb911a160485fcc52f87d9`。
- 复用 PR #67 `82058dea652e069069e2d1ffda0d8b1f2f856535` 四个布局源码/测试文件，保留 #66 的原子证据及目视门。
- [完整源码包](gork-test-kit.zip)：551 个源码/受控夹具文件，含源码、候选、矩阵和回传模板，非 Windows 运行时。
- ZIP 大小：1,324,799 bytes；SHA256：`63459f52ffa73b388022e909e77a47fa4fef96b584aadcc0cd4ac9c2fa21bcd1`。
- 内层 source.zip SHA256：`ffd07b162b8080d6a478c7f9273aaa2fac0cea54ede5401b55476d46580f8ff2`。

后续仅增加交测附件的 HEAD 不作为源码测试 pin。原程序、原 CAD、旧包和原生测试 pin 保留；只在新目录验收。

## 核对后的修改

1. 接入布局锚点/重建后测量/有限次数收敛/标题栏避让，比例和图框验证不放宽；并保留注解名称/位置/文字重开核对及 reviewing/accepted 门。
2. `LayoutDoesNotFit` 附结构化尺寸、边界、图纸大小、比例和备选方案，失败页原子 JSON 与 trial cell 保留；界面显示部分生成数量和明确需用户选择的方案，不自动改变比例或重跑。
3. 保留 Windows 路径、UTF-8、baseline 缺失和打包修复；仅打包三个登记的合成 DXF，恢复测试中文，拆开 symlink/hardlink 检查，权限不足显式跳过。

完整来源核对、变更和未解决项：[docs/test-followup-review.md](../../docs/test-followup-review.md)。

## 测试与边界

`validation.json` / `targeted-tests.log`：145 项相关模拟/文件/包检查通过，0 失败、0 错误、0 跳过。不是全面回归、Windows/SolidWorks 或人工目视结论，本轮未重跑桌面。

`package-verification.json`：完整新源码包的 pin、矩阵、文件哈希及新目录导入已核对；未执行安装后代码或启动 SolidWorks。

旧报告中的 Windows 1093 项结果只属于 `36630fb`；D4 的 3/6 属于 `82058de`，不能附给本批组合。实际放不下的 A3@1:10、A2@1:5、A3@1:5 保持明确拒绝，三个生成格仍需具名目视接受；D6 和旧 p248 固定面板失败不自动销项。

Gork 下轮在新目录固定本源码 pin，先做 Windows 源包/UTF-8/路径检查，再做六格 D4 和结构化拒绝、候选选择、页证据、人工目视门及原有恢复/幂等/Lease 检查。候选仅是纸面估算，需用户选择后原生和目视验证。不得为了全绿缩小比例或删除视图；manufacturing_approved 始终 false。

建模域增强代码仍隔离开发，本 PR 没有将未提交模块混入交付或统计为已测试。
