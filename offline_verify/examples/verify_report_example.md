# 离线验证报告（Issue #25 扩展模块 ⑥）

- 生成时间（UTC）：2026-10-24T14:38:57.642295+00:00
- 运行器版本：1.0.0
- 检出根：`/tmp/devcheck`
- 退出码：1
- 退出原因：baseline diffs: recovery-guards; suites missing: bridge-build-reopen, dxf-extract, feature-tree, dependency-engine
- 完整（全部套件在场且通过且基线一致）：否

## 汇总

| 项目 | 数 |
|---|---|
| 套件总数 | 13 |
| 套件在场 | 9 |
| 套件缺失 | 4 |
| 套件通过 | 9 |
| 套件失败/出错 | 0 |
| 用例执行 | 94 |
| 用例通过 | 94 |
| 用例失败 | 0 |
| 用例出错 | 0 |
| 用例跳过 | 0 |
| 基线一致 | 8 |
| 基线差异 | 1 |

## 各套件

| 套件 | 状态 | 执行/通过/失败/出错/跳过 | 基线 | 来源 |
|---|---|---|---|---|
| bridge-contract | pass | 17/17/0/0/0 | 一致（17） | PR #26 @ 7363fe49 |
| bridge-wiring | pass | 8/8/0/0/0 | 一致（8） | PR #31 @ f8b20580 |
| bridge-build-reopen | missing | 0/0/0/0/0 | 缺失（不比对） | PR #32 @ e08b8509 |
| pipeline | pass | 14/14/0/0/0 | 一致（14） | PR #23 @ 9d65352a |
| issue19-ckpt | pass | 14/14/0/0/0 | 一致（14） | PR #23 @ 9d65352a |
| no-default-k | pass | 5/5/0/0/0 | 一致（5） | PR #29 @ a7e171cb |
| bend-allowance | pass | 6/6/0/0/0 | 一致（6） | PR #29 @ a7e171cb |
| p0-gork | pass | 10/10/0/0/0 | 一致（10） | PR #29 @ a7e171cb |
| recovery-guards | pass | 8/8/0/0/0 | 差异：实测 8，期望 7（delta +1） | PR #30 @ d392b74d |
| dxf-extract | missing | 0/0/0/0/0 | 缺失（不比对） | PR #35 @ f9dd625d |
| feature-tree | missing | 0/0/0/0/0 | 缺失（不比对） | PR #36 @ 1a8b30fb |
| dependency-engine | missing | 0/0/0/0/0 | 缺失（不比对） | PR #37 @ 0c722db2 |
| offline-verify-self | pass | 12/12/0/0/0 | 一致（12） | PR #module-6 @ this-branch |

## 缺失套件（分支未合并，绝不计入通过）

- bridge-build-reopen
- dxf-extract
- feature-tree
- dependency-engine

## 原则

- merge != validation: every Windows / SolidWorks item is pending_windows_validation. Mock/offline passes are never native acceptance; a missing suite is never a pass.
- 合并 ≠ 验证通过：本报告只证明离线 mock/回归通过，Windows / SolidWorks 实机验收见 WINDOWS_ACCEPTANCE_PACK.md，全部标 pending_windows_validation。
