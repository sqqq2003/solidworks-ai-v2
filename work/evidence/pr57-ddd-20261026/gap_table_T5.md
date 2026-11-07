# T5 车件尺寸对照 · 差距表

- SHA：`9544d3ca27b5f4b255b60a3eab3061af8a930fc2`
- 脚本：`run_turned_accept.py`（OUT 内适配副本 `run_turned_accept_out.py`，输出重定向到 OUT，未写桌面）
- 夹具：`C:\Users\yue\Desktop\chejian_cmp\dxf_fixtures\`（f09/f11/f15/f19）
- 成品对照：`C:\Users\yue\Desktop\QL-5050PX左右驱动一体封箱机\车件图\`

## 结果汇总

| 夹具 | 名称 | stock | 期望 LWH (mm) | plan 长度 | 生成件 LWH (mm) | 成品 LWH (mm) | 结论 |
|---|---|---|---|---|---|---|---|
| f09 | 主动轴 | revolve | 166 × 28 × 28 | 166.0 | **生成失败** | (量测失败·见下) | **FAIL** |
| f11 | 锁定柱 | hex | 75 × 19.63 × 17 | 75.0 | 75.0 × 19.630 × 17.0 | 75.0 × 19.630 × 17.026 | **PASS** ✓ |
| f15 | 导轮轴 | revolve | 55 × 10 × 10 | 54.968 | **生成失败** | 55.0 × 10.0 × 10.0 | **FAIL** |
| f19 | 延长轴 | revolve | 385 × 15 × 15 | 385.0 | **生成失败** | 385.0 × 15.0 × 15.0 | **FAIL** |

## 关键发现

1. **f11 锁定柱（hex）PASS**：生成件外包 (75.0, 19.630, 17.0) 完全命中期望值，与成品 (75.0, 19.630, 17.026) 误差 < 0.03 mm（六角对边 17 精确一致）。

2. **f09/f15/f19（revolve 类）FAIL**：三个车削件均在 `generate_turned_part` 的 `draw()` 阶段抛
   `SolidWorksGenerationError: 旋转轮廓没有闭合轮廓，已中止保存，避免生成片体。`
   plan 阶段轴向长度/最大半径解析正确（166.0 / 54.97 / 385.0，max_radius 14/5/7.5），但旋转轮廓草图未闭合，
   代码主动中止保存以避免生成片体（非崩溃、非 COM 断开）。

3. **f09 成品量测 COM 初始化问题**：f09 是首个 case 且生成即失败，随后 `measure_sldprt` 首次
   `Dispatch("SldWorks.Application")` 报 `com_error: 尚未调用 CoInitialize`（脚本在生成失败分支下未 CoInitialize）。
   后续 f11/f15/f19 的 fin_measure 正常（f11 成功生成时 SW 已初始化）。属 cad2sw 脚本健壮性问题，非仓库缺陷。

4. 生成失败的三个 case 均无 .SLDPRT 产物落盘（符合"避免生成片体"的安全中止语义）。

## 与仓库 turned 路径的一致性

仓库 `src/turned_part.py`（1946 行）与 cad2sw-dl 旧版副本（1776 行）在 f09/f15/f19 上表现一致，
均为"旋转轮廓没有闭合轮廓"中止保存，确认这是同一 turned 实现链路的既有缺陷（revolve 轮廓闭合），
与 PR#57 的 COM 硬化主题无关，但构成本轮车件验收的 fail 项。
