# Python ↔ C# SolidWorks 桥接契约（Issue #25）

> 契约版本：`sw-bridge/1`。本文档与 `src/SwBridge.cs`（C# 侧）、`python/bridge_client.py`（Python 侧）共同构成契约实现。
> 证据等级：本文档与 mock 测试属于**离线验证**；一切涉及真实 SolidWorks 的行为均为 **pending_windows_validation**，以 Gork 的 Windows 实机证据为准，mock 通过绝不写成实机通过。

## 1. 为什么需要这个桥接

Python + win32com 跨进程驱动 SolidWorks 已被证明脆弱：p248 折弯 4/4 全过、产物落盘后，Python 进程在 COM 卸载阶段崩溃（EXIT=139 / 0xC0000005，见 REVIEW.md）。Python 的 GC 时序不确定，`CoUninitialize()` 时仍有存活 COM 包装对象是头号嫌疑。

桥接把职责切开：

- **Python 侧**：出计划（特征树 IR、参数图）、做离线计算、写 checkpoint、做验收判定。Python 不再直接持有 SolidWorks COM 对象。
- **C# 侧**：在单一 STA 线程上持有全部 COM 对象、执行建模/重建/读回、按确定顺序释放。C# 的释放语义（显式 `Marshal.ReleaseComObject` + `GC.Collect()`）比 Python 的 GC 时序确定得多。

本桥接是**传输 + 执行层**，不是第三套数组桥：SW2022 数学数组编组（VT_ARRAY|VT_R8 / `ArrayData`）继续复用 PR #20 的 `sw_math_arrays.py` 约定，两者组合、不竞争、不重复。

## 2. 传输选择：命名管道 + JSON 行协议

**选定：Windows 命名管道（Named Pipe），每行一条 JSON 消息。**

| 候选 | 结论 | 理由 |
|---|---|---|
| 命名管道 | ✅ 选定 | 本机 IPC、Windows 原生、无网络暴露面、与 SolidWorks 同机部署零配置、字节流可按行分帧 |
| HTTP 本地回环 | 备选 | 实现简单，但多一个端口占用/防火墙面，且 HTTP 语义（重试、keep-alive）对"恰好一次执行"反而是负担 |
| 标准输入输出管道 | 否决 | SolidWorks 子进程的 stdout 常被占用/重定向，分帧与日志混杂风险高 |

安全边界：管道名固定前缀 `sw-bridge`，仅本机可连；不监听 TCP，绝不跨机器。超时由调用方强制（见 §6）。

## 3. 消息格式

请求（Python → C#）：

```json
{
  "protocol": "sw-bridge/1",
  "id": "<uuid hex, 用于请求-响应配对>",
  "method": "<方法名>",
  "units": "mm",
  "params": { "...": "..." }
}
```

响应（C# → Python）：

```json
{ "protocol": "sw-bridge/1", "id": "<原请求 id>", "ok": true, "result": { "...": "..." } }
{ "protocol": "sw-bridge/1", "id": "<原请求 id>", "ok": false, "error": "<人类可读原因>" }
```

字段规则：

- `protocol` 必须为 `sw-bridge/1`，否则拒收。
- `id` 必须回显原值；错配 id 的响应视为协议错误。
- `units` 必须为 `"mm"`；任何其他值拒收（单位错误是工程事故的头号来源，宁可拒收不猜）。

方法表：

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `hello` | — | `{bridge, protocol}` | 握手 |
| `spawn` | `{sldworks_exe?}` | `{pid, owned}` | 桥接 spawn SLDWORKS.exe 并做 PID 绑定证明（见 §4）；mock 返回固定 pid |
| `create_empty_document` | `{title}` | `{title, owned}` | 创建空文档并登记为 owned |
| `close_document` | `{title}` | `{title, closed}` | 只关 owned 文档；关 foreign 标题返回错误 |
| `list_titles` | — | `{titles}` | 列出当前打开的文档标题 |
| `exit_app` | — | `{exit_requested}` | 仅当 owned 文档已空时才允许；否则拒绝 |
| `teardown_report` | — | `{exit_code}` | 上次收尾的进程退出码（整数，可为非零） |
| `build` | 见 §12 | `{title, owned, bend_count, auto_bent, auto_bend_failed_count, part}` | 按已验证计划建原生钣金件并保存到工作副本路径（S1 执行） |
| `reopen` | 见 §12 | `{reopened, rebuilt, feature_types, editable, bend_feature_count, completed_bend_count, thickness_mm, radius_mm, k_factor}` | 重开已保存件并读回原生特征与钣金参数（S2 执行） |

## 4. 独占会话规则（与 sw_session.py / sw_owned_launch.py 同款纪律）

1. **只 spawn，不附着**：桥接只操作自己 spawn 的 SLDWORKS.exe 进程；禁止附着到用户已打开的 SolidWorks。
2. **PID 绑定证明**：`GetProcessID()` 必须等于 spawn 的 PID；新进程内必须零文档，否则整批任务拒绝开始，进程保持原样不动。
3. **所有权登记**：每个文档创建时登记 title + handle；`close_document` / `exit_app` 前核对登记表，foreign 标题一律拒绝。
4. **零文档才 ExitApp**：`list_titles` 非空时拒绝 `exit_app`；`exit_app` 被拒不是失败，是保护。
5. **绝不按进程名杀进程**：回收只针对确切 spawn 的 PID；`terminate`（如需）只发给该 PID，且仅在 `left_open_for_recovery` 语义下由人工决定。
6. **工作副本隔离**：一切写操作只发生在工作副本上；客户原件只读，绝不覆盖。

## 5. 参数单位（硬规则）

- 长度：**mm**；角度：**度**；质量/力等如后续扩展，必须在消息里显式标注单位字段。
- 角度弧度只出现在公式内部，消息层面一律用度。
- 单位换算函数必须显式命名（`mm_to_m` / `m_to_mm`），禁止隐式换算。
- 坐标数组单位随消息单位走（mm），C# 侧在调 SW 数学 API 前自行换算为米（SW 内部单位为米），换算点唯一、不许散落在各处。

## 6. 数组类型（复用 PR #20 约定，不另起一套）

- 点：3 个 double；变换：16 个 double；数组元素必须全部有限（finite），长度必须精确匹配，否则拒绝。
- 编组规则：`double[]` ↔ VT_ARRAY|VT_R8 SAFEARRAY；`IMathPoint.ArrayData` 往返后必须与输入一致（容差 1e-12），见 `sw_math_arrays.py` 的 `create_point` / `create_transform` / `oracle`。
- Python-COM 路径继续用 `sw_math_arrays.py`；C# 路径用 .NET 的 double[] 封送；两条路径的**语义**（长度、有限性、往返容差）必须一致，测试用同一组 oracle 用例。

## 7. 日志格式

结构化日志行（JSON），字段固定：

```json
{ "stage": "S5", "event": "close_documents", "owned_docs": ["..."],
  "pid": 12345, "elapsed_ms": 12.3 }
```

- `stage` 取值 S0–S5，与 PR #23 的 checkpoint 阶段一致。
- 每个阶段起止各记一行；`owned_docs` 记关前/关后清单。
- 日志与 checkpoint 分离：日志是过程记录，checkpoint（`ckpt-<阶段>.json`，含 plan_id、时间戳、产物路径 + SHA256）是可恢复的证据；两者都写，互不替代。

## 8. 异常 / 超时 / 退出隔离

- **超时**：每个请求带调用方超时（默认 30s；建模类请求由调用方按任务放大）。超时即失败，不重试、不猜测对方状态；超时后的会话视为不可信，后续请求必须先重建会话。
- **异常**：错误响应只含人类可读原因 + 方法名，不含堆栈、不含客户文件路径。
- **退出隔离（重点，针对 #19 的崩溃类）**：
  1. 收尾 5 步固定顺序（见 §9），任何一步失败都如实记录，不跳步。
  2. 硬崩溃（进程直接退出、EXIT=139 / 0xC0000005）会跳过全部 `finally`，因此证据必须在**运行中**落盘（checkpoint），不能只在最后写。
  3. 崩溃遗留的 lock 与 staging 由下一 run 按 PR #23 规则处理（死锁归档、孤儿隔离），绝不静默删除。
  4. 退出码是**记录值**，不是断言值：0 与非零都要原样写进 accept 报告；非零退出码的 run 只能写"折弯通过、收尾待定"，不能写"全流程稳定"。

## 9. 释放顺序（硬规则，#19 崩溃的直接对策）

```
close_documents        # 逐个 CloseDoc owned 文档
  -> enumerate_titles  # 应为空；非空则拒绝继续
  -> exit_app          # 需要活着的 app 包装对象，所以先于释放
  -> release_wrappers  # 按创建逆序显式释放每个 COM 包装
  -> GC.Collect + WaitForPendingFinalizers
  -> process_exit      # 读取并记录进程退出码
```

Python-COM 路径的对应规则：先放引用（`del` + `gc.collect()`），**最后**才 `CoUninitialize()`。`reopen_inspect` 的 finally 里在仍有存活包装对象时调 `CoUninitialize()` 是 dev/cloud-ai 现状中的头号嫌疑点（见 REVIEW.md），PR #23 已在分支上修正了该函数的释放顺序，本桥接的 C# 侧执行同一顺序。

## 10. 与 PR #23 checkpoint 的衔接（不重复、不冲突）

| PR #23 已有 | 本桥接 |
|---|---|
| `ckpt-<阶段>.json` 写入/读取/链校验 | 桥接的 S1/S2/S5 证据以同样 shape 输出，供 checkpoint 直接收录 |
| `RunLock`（owner.json + 心跳 + 死锁归档） | 桥接不碰 lock；调用方（run_plan）仍是 lock 的唯一所有者 |
| 孤儿 staging 隔离（`orphaned/`） | 桥接不碰 staging 目录；崩溃现场由调用方打包 |
| `TeardownRecorder` 5 步日志 | 桥接的收尾记录字段与之一致（stage/event/owned_docs/pid/elapsed_ms），可直接并入同一报告 |
| `run_minimal_teardown` | 桥接提供对应的最小收尾入口（spawn → 零文档 → ExitApp → 退出码），供 Gork 二分定位 |

## 11. 待确认项（本契约不擅自决定）

- SW2022 与 SW2025 的 API 行为差异对桥接的影响（待 Gork 在两个版本上实测后写进附录）。
- 命名管道在目标 Windows 环境的权限策略（普通用户能否创建/连接同名管道）。
- 大装配场景下单条消息的体积上限（目前不定上限，首批只跑单件钣金）。
- 以上三项在实机验证前均为 pending_windows_validation。

## 12. build / reopen 方法（本批新增，Issue #25 batch 2）

### 12.1 build（S1 执行）

请求 `params`（单位一律 mm / 度，`units` 仍须为 `"mm"`）：

```json
{
  "plan_id": "<build_plan 的 plan_id>",
  "title": "<零件文档标题，如 part.SLDPRT>",
  "part_path": "<run staging 内的保存路径，工作副本>",
  "thickness_mm": 2.5, "radius_mm": 1.0, "angle_degrees": 90.0,
  "k_factor": 0.4, "flip_direction": false,
  "bend_count": 1,
  "idempotency_key": "<plan_id:S1:build 的 sha256，见 §12.4>"
}
```

- `thickness_mm / radius_mm / angle_degrees / k_factor / flip_direction`
  全部是**每单显式输入**：缺任何一项，服务端返回 ok:false，错误中注明
  pending_confirmation；Python 客户端在发请求前同样先校验，缺项直接
  抛 MissingParameterError。**绝无默认值**（t=2.5 / K=0.36 只是本厂一次
  实测用例，不是默认值，见 bridge_client.py）。
- `part_path` 只能是 run 的 staging 工作副本路径：桥接只写该路径，
  绝不写客户原件，绝不写其他目录。
- `bend_count` 是计划中的折弯条数（整数计数，不是几何）；mock 回显
  该计数，实机由建模结果决定。
- 返回 `{title, owned, bend_count, auto_bent, auto_bend_failed_count,
  part}`，形状与 port `generate()` 的结果对齐，`run_plan` 的 S1 检查
  （非模拟运行时 `auto_bent` 必须真、`auto_bend_failed_count` 必须 0）
  对桥接结果同样适用。
- **几何引用（本批的诚实边界）**：build 目前只用 `plan_id` 引用已验证
  计划，不在消息里传完整轮廓 / 孔 / 折弯线几何。完整几何 IR 的传输
  方式（消息内嵌还是工作副本文件引用）是 RealSwApp build 宣称完成前
  必须先定稿的设计项；mock 与骨架不掩盖这一点。

### 12.2 reopen（S2 执行）

请求 `params`：`{plan_id, title, part_path, idempotency_key}`。

- 语义与 port `reopen_inspect()` 一致：**重开已保存件**（绝不是检查
  未保存的 live 句柄），重建，读回特征树、钣金定义、CustomBendAllowance。
- 返回 `{reopened, rebuilt, feature_types, editable, bend_feature_count,
  completed_bend_count, thickness_mm, radius_mm, k_factor}`，其中
  thickness / radius / k_factor 是**文档实测读回值**，调用方用
  `validate_native` 对照计划参数比对（容差 1e-6），不一致即失败。
  mock 返回固定形状的 canned 读回（见 bridge_client.py 的
  MOCK_READBACK 与 SwBridge.cs 的 MockSwApp 注释），不是实测、不是默认值。
- 重开后检查文档必须**不保存地关闭**，恢复检查前的抑制状态
  （与 `measure_folded_and_flat` 同款纪律）。

### 12.3 错误映射

| 情况 | 服务端响应 | Python 客户端 | 调用方（run_plan）处理 |
|---|---|---|---|
| 缺每单参数 | ok:false，注明 pending_confirmation | MissingParameterError | 当阶段 fallback 到 port，grade mock + fallback_reason |
| 参数越界（K ∉ [0,1]、角度 ∉ (0,180)、t ≤ 0、R < 0） | ok:false | BridgeError（ValueError 文本） | 当阶段 fallback 到 port |
| 欲关 / 欲读非 owned 文档 | ok:false，注明 unowned | OwnershipError | 当阶段 fallback 到 port |
| 方法执行失败（建模 / 重开异常） | ok:false | BridgeError | 当阶段 fallback 到 port，**不写 crash 包**（port 回落即恢复手段） |
| 请求超时 | （无响应） | BridgeTimeoutError | 当阶段 fallback 到 port；超时后的会话视为不可信，后续阶段先重建会话 |
| 会话丢失（spawn PID 失配、list_titles 失败） | ok:false 或无响应 | BridgeError / 超时 | 当阶段 fallback 到 port |

- 错误响应只含人类可读原因 + 方法名，不含堆栈、不含客户文件路径。
- **退出隔离**：build / reopen 失败绝不杀会话、绝不 ExitApp、绝不碰
  无关进程；S5 的收尾纪律（失败记证据 + crash 包、产物不反发布）
  不受本批影响。

### 12.4 幂等键

- `idempotency_key` 由调用方按 `(plan_id, 阶段, 方法)` 确定性生成
  （sha256 hex），同一计划重跑重放同一键。
- 服务端对同一键 + 同一参数的 build **不得重复建模**：mock 按键记忆
  首次结果并原样返回；实机实现必须同样保证（未实现前不得宣称
  build 已实机可用）。
- reopen 是只读操作，键仅用于请求追踪，不做结果记忆。
