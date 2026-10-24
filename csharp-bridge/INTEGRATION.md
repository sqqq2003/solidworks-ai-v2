# 集成建议、风险清单与 Gork 验收矩阵（Issue #25）

> 集成原则：桥接只新增，不改动现有引擎文件；与 Codex 的 #24 滚筒改型零文件重叠；
> 与 PR #23 的 checkpoint/收尾机制衔接，不重复、不冲突。

## 1. 桥接如何接入现有 Python 引擎

`run_plan` 的 S1 / S2 / S5 三个阶段是桥接的接入点；S0（计划锁定）、S3（导出）、S4（验收落盘）保持现有逻辑不动。

```
run_plan (Python, 编排层)
  S0 计划锁定            [不变：plan 哈希、code_sha256、pending 检查]
  S1 生成               [桥接执行] Python 发 build 请求 -> C# 建原生特征
                         -> C# 回传 bend_count / auto_bent / part 路径
                         -> Python 写 ckpt-S1.json（PR #23 格式）
  S2 重开检查            [桥接执行] Python 发 reopen 请求 -> C# 重开读回
                         -> 读回 thickness / radius / k_factor / feature_types
                         -> Python 跑 validate_native，不一致即失败
  S3 导出               [不变：现有 export_flat；DXF 非空校验保留]
  S4 验收落盘            [不变：result.json 原子 rename]
  S5 收尾               [桥接执行] Python 发 teardown 请求 -> C# 按 5 步
                         收尾 -> 回传步骤记录 + 进程退出码
                         -> Python 并入 TeardownRecorder 报告
```

- **Linux CI 模式**：S1/S2/S5 走 Python mock（`MockSheetMetalPort` / `MockTransport`），只验证契约与流程，不产生任何"原生通过"结论。
- **Windows 实机模式**：S1/S2/S5 走 C# 桥接；Python 侧的 mock 代码在实机路径上**一行都不执行**，避免 mock 结果混入实机证据。
- **checkpoint 互通**：桥接输出的证据字段与 PR #23 的 `ckpt-<阶段>.json` 同形（plan_id、时间戳、产物路径 + SHA256、证据摘要），Python 侧直接收录，不做二次转换。
- **锁与 staging**：`RunLock` 与孤儿 staging 隔离仍归 `run_plan` 所有，桥接不碰 lock 目录、不碰 staging 目录、不删任何文件。
- **数组桥接分工**：数学数组编组继续走 PR #20 `sw_math_arrays.py` 的约定；本桥接只负责传输与执行，不另起一套编组规则。两者组合关系见 CONTRACT.md §6。

## 2. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | C# 侧 COM 线程模型错误（非 STA 调用） | 调用失败或随机崩溃 | 全部 COM 调用固定在单一 STA 线程；非 STA 调用直接拒绝 |
| R2 | 释放顺序错误重现 #19 崩溃 | 进程退出 AV，前功尽弃 | 5 步固定顺序 + 逆序释放 + GC 后才退出；先跑最小收尾复现再跑全流程 |
| R3 | 命名管道权限（目标 Windows 普通用户能否创建/连接） | 桥接无法启动 | 首批只跑单机同用户场景；权限问题实测后写进 CONTRACT 附录 |
| R4 | SW2022 vs SW2025 API 行为差异 | 桥接在一版本过、另一版本不过 | 验收注明实测版本；API 适配层隔离版本差异 |
| R5 | #17 与 #20 两套数组桥接关系未定性 | 重复建设或错误取代 | Gork 定性前，两套桥接都保留，本桥接不替任何一方表态（见 REVIEW.md §6.4） |
| R6 | PR #22 标题提示的 dual-source 复测失败 | #20 桥接可能有未暴露问题 | 正文未读：Gork 确认失败性质前，不许写 #20 桥接"已验证" |
| R7 | 超时后会话状态未知 | 误把半截产物当完成 | 超时即判会话不可信，必须重建会话后从 checkpoint 续跑 |
| R8 | 大装配消息体积 | 管道阻塞或截断 | 首批只跑单件钣金；大装配上限待实测后定 |
| R9 | 默认 K 值误用（`BendAllowanceSpec` 的 0.44） | 用通用值冒充某单制造依据 | 桥接客户端缺 K 即报错 pending；调用方必须显式传每单 K |
| R10 | 与 Codex #24 同文件写入冲突 | 互相覆盖 | 本批只写 `csharp-bridge/` 新目录，零改动现有文件 |

## 3. 给 Gork 的 Windows 验收测试矩阵（一次性）

> 验收口径：四项齐全才写"全流程稳定"，缺任何一项只能写"部分通过 + 待定项"。
> 每次验收必须记录：SW 版本、会话归属（独占 spawn / warm-reuse）、进程 PID、退出码。

| # | 测试 | 步骤 | 通过标准 | 证据 |
|---|---|---|---|---|
| A1 | 最小收尾复现 | C# 桥接 spawn → 零文档 → ExitApp → 退出，连跑 3 次 | 3 次退出码均为 0，无 AV | teardown 5 步日志 + 退出码 |
| A2 | p248 全流程 | Step0：4/4 折弯 + 重开读回（thickness/radius/k 与计划一致）+ DXF 非空 + 退出码 | 四项齐全；缺退出码只能写"折弯通过、收尾待定" | accept JSON（必须由 runner 正常写出，**不再事后重建**）+ 5 步日志 |
| A3 | oracle 验证 | PR #20 `sw_math_arrays.oracle` 在 SW2022 上跑用例 | max_dev ≤ 1e-10，且往返后进程能干净退出 | oracle 结果 JSON + 退出码 |
| A4 | 桥接往返 | C# 侧 echo：3 点数组与 16 变换数组往返 | 与输入精确一致（容差 1e-12） | 往返记录 |
| A5 | 死锁与续跑 | 人为留旧 lock + 孤儿 staging，跑新版 | 识别并归档旧 lock，续跑不丢已完成的 S1/S2 产物 | 归档记录 + 续跑 checkpoint 链 |
| A6 | 桥接定性 | 确认 #17 与 #20 两套桥接的关系；确认 PR #22 dual-source 失败的性质 | 在 PR 描述中明确写出取代/并存/分工结论 | 文字结论 + 链接 |
| A7 | 缺省保护 | 故意不传 K（或 t）调桥接 | 桥接返回 pending_confirmation，不用任何默认值顶替 | 错误响应记录 |
| A8 | 证据交付 | 全套验收跑完后 | accept JSON 由 runner 正常写出；SW 保持运行供复查时注明"SW left running"，不得写成已干净退出 | accept JSON + 日志 |

## 4. 未测清单（本批交付时全部未测，待 Windows）

- C# 代码编译（本机无 .NET SDK；Windows + .NET SDK 上编译待验）。
- C# 命名管道服务器的实际启动、连接与消息往返。
- RealSwApp 的全部内容（`SOLIDWORKS_INTEROP` 分支，含 PID 绑定、建空文档、ExitApp）。
- 桥接在 SW2022 与 SW2025 上的行为。
- 桥接与 `run_plan` 的真实接线（本批只给出了接线设计与 mock 客户端，未改 `run_plan` 代码——改 `run_plan` 属于下一批，需单独评审，避免与 #23 的合并冲突）。
- 以上全部标 pending_windows_validation。
