# 统一交付候选：源码、审核工作流与测试回传

本批以 dev/cloud-ai 的 62a9c913d89c5b01d261f997117bbce27966f3c4 为基线，
复用 PR #62 的设计平台、Issue50、统一规划、四类模型协议与实例共存能力，以及 PR #58
的已审批动作转换和单参数验收工具。新分支集中交付，不移动旧 PR 的测试 pin，不覆盖用户安装和 CAD。
完整来源见 delivery/unified-candidate/source-versions.json。

最新 dev 中的诊断日志、DXF 概览、钣金批量审核、缩放保孔、工程图试验、旋转闭合修复、
COM 断开分类/同 PID 重连、启动空白文档和引用归属处理均保留。
ROT 连接同时保留新的 IUnknown→IDispatch 转换，只定位新进程对应的 PID 项。
旧锚点生命周期测试转入 tests/history，当前自动回归使用最新 DDD/S2 契约；不是删掉归属或退出检查。
原有 36 项离线特征合约的几何/标注识别实现已复用并与最新原生生成代码合并，
更改后的真实车件/钣金仍需要按同一新候选重验，不能沿用历史实机通过。

## 一、统一源码候选包

在干净的 Git checkout 中：

```powershell
python work/delivery.py candidate --out <仓库外的新目录> --revision <完整40位提交SHA>
python work/delivery.py verify-candidate <候选目录>
```

输出 source.zip、candidate.json、matrix.json、submission-template.json、READ-FIRST.txt。
复用 prepare_test_handoff 的版本化源码白名单，补齐 geometry_ir、feature_tree 等依赖目录。
不打包客户 CAD、密钥、未跟踪文件、历史 Git、运行日志或旧验收结果。
源码包带 HANDOFF 文件哈希；候选带源码 ZIP 和矩阵哈希及 candidate_id。
Git 分支变化、未提交修改、打包中途变化、已有输出目录均拒绝。

无 .git 的云端固定源码快照可显式传 --source-index <index.json>；格式为 schema_version=1、
source_revision（完整 SHA）、files（仓库相对路径→Git blob SHA1）。只接受与该索引逐字节匹配的文件，
不读取索引之外的源码，不跟随目录或文件符号链接。索引应来自被审核的固定 GitHub tree，
它不是签名或自动工程放行。

本候选是源码包，不是 Windows 免安装运行时。解压到新目录，先执行：

```powershell
python work/verify_test_handoff.py .
python -m pip install -r requirements-cloud.txt
python app.py
```

现有 work/build_portable.py 继续作为本机 Windows x64 Python 3.14 / Tk9 发行环境的打包入口，
现在复用同一套源码收集规则，记录真实 Git revision，拒绝脏源码；云端不能生成并验收 Windows DLL 包。
在已验证的 Windows 环境运行 `python work/build_portable.py --output <新候选目录>`，
不要在用户原安装目录运行覆盖升级。

## 二、可持续保存的改型工作区

桌面左侧“项目交付 / 验收”提供创建方案、读取状态、具名审核、Windows 副本执行和回传核对。
命令行是同一套 API：

```powershell
python work/delivery.py prepare examples/unified-project.json --out <新工作区>
python work/delivery.py status <工作区>
python work/delivery.py approve <工作区> --reviewer "工程审核人" --review-sha256 <影响分析摘要>
python work/delivery.py execute <工作区> --sw-exe "<安装目录>\SLDWORKS.exe" --approval-sha256 <审核记录摘要>
```

工作流复用 unified_project.build_release、design_review.record_approval 和 roller_variant.native.run_native，
不是第二套建模/事务框架。保存 request、规划、影响分析和文件/原件/代码哈希；输入、模型、规划或实现变化
都会使旧审核失效。具名审核只记录本方案认可，原生执行仍经过已有会话、Pack-and-Go、映射和接口校验。
执行需要 Windows 和有效安装路径，只写新副本；每个工作区只有一个排他执行 claim。
失败后保留 claim 和诊断，不会偷偷重试未知 CAD 状态。

现有可执行闭环首先覆盖“已有滚筒模型改型”；整机、二维建模和工程图继续走原工作台/CLI。
合成示例没有真实模型和完整意图，预期为 inputs_required/review_required（退出3），不能为测试方便自动补齐确认。
实际模型路径应为本机绝对路径，映射/测量/保护接口/依赖清单必须来自工程审核。

## 三、Gork 证据收件与待办

矩阵和回传模板来自同一个源码候选。按 Windows/离线实际执行填记录，不能把 mock 结果改成 native。

```powershell
python work/delivery.py audit <matrix.json> <submission.json> --evidence-root <证据目录> --out <新报告目录>
python work/delivery.py diagnose <诊断日志.zip> --out <新的诊断报告.json>
```

审核复用 test_handoff_audit，核对完整源码 SHA、检查项、四态、环境、退出码、证据路径和 SHA256；
原生 passed 还须声明 simulated_only=false、spawned_pid_and_live_handle 和 attached_existing=false。
输出 audit.json 与 repair-tasks.json，失败生成 P0 修复待办，缺项/过期/降级生成补证或复核待办。
报告的 passed 仅表示声明覆盖/文件完整性一致，native_acceptance 仍要求独立复核，manufacturing_approved 永远为 false。

诊断 ZIP 只在内存解析有界 JSONL，不解压、不运行任何成员，支持当前日志 details 字段，
输出失败定位、事件统计和去重问题。日志含本地文件名时仍应留在本地，不自动上传。
原来上传的诊断 ZIP 当前执行环境已不保留，因此本批只验证合成诊断样本，未伪称重新读取过旧附件。

## 四、交测顺序及限制

Gork 下一组使用本 PR 的一个固定源码 pin，新目录安装，不中断当前旧 pin 任务：

1. 验证候选 ZIP/源码哈希，跑离线回归及桌面/API模拟；真实服务由操作者在本机配置密钥。
2. 旧 SolidWorks 窗口保留，新任务另开 PID；核对旧文档未被保存、改动或关闭。
3. 原 DWG 分析→计划，已有滚筒800改型方案→人工审核→副本执行→保存重开/原件哈希。
4. 钣金重建/展开、真实车件、装配运动干涉、图纸/BOM、引用及退出稳定性，统一收集日志。
5. 填回传模板，在候选矩阵下核对；缺 OEM 映射/许可/环境/证据就保留 review_required。

未完成的实机项保持 not_run。任意CAD语义识别、全部厂商私有模型协议、完整整机工程放行、
可自动完成一切故障的修复器均不在本批宣称范围。自动待办不是自动改图或自动批准。
