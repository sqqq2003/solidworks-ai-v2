# 合并批次：S2 复测、证据绑定与统一收件

本批叠加于 7c787de 的会话保活、原生数学接口与单次复测工具。沿用 xi3wwg 执行者与任务依赖；本批只提交一次测试。不增加 CAD 并发，不覆盖正在测试的目录。

## 开发内容

- prepare_s2_retest.py 保存管线 code_sha256，绑定测试前源码，不采信报告自己填写的版本。
- prepare_test_batch.py 从现有 fixture 回执生成统一清单，核对原始样例未变化，记录报告字节哈希；不执行其中的 command_argv。
- check_test_batch.py 一次核查全部清单项：源、源码、轮廓、参数、原生产物、原生读回和干净退出；缺件/坏 JSON 不会遮蔽后续项。
- 每个执行者/案例组合唯一，所有清单文件路径限制在收件根目录；输出文件只新建。

## 一次交接流程

1. 固定本批最终完整提交 SHA。在新目录 checkout；如果上一轮已经开始，先完成上一轮，不中途更新运行目录。先回传实际加载 SHA。
2. 跑 work/run_cloud_tests.py；这只有离线模拟含义。C# 未有 SDK 编译、Windows 原生与工程验收分别记录。
3. 按 s2-retest-20261024.md，WB 先执行合成 fixture，正常退出后才轮到 Qoder。两者各用新目录、新 prepare_s2_retest.py 回执，不复用旧版本缺少 code_sha256 的回执。
4. 收集 stdout 的完整 JSON 为各自 result.json；保留 session.log、stderr、进程退出码及产物位置。不要改写 result.json 里的 output_dir 来迁就收件。报告引用的原生产物需仍在本机可读，否则保持未验证。
5. 两份回执完成后，在本机统一收件；仅报告和清单路径用相对于 --root 的路径。示例目录名应替换为本轮真实目录名：

```powershell
python -X utf8 work/prepare_test_batch.py --root 'D:\工程\钣金导入' --case WB wb_s2keep_NEW wb_s2keep_NEW/result.json --case Qoder qoder_s2keep_NEW qoder_s2keep_NEW/result.json --out 'D:\工程\钣金导入\batch-NEW.json'
python -X utf8 work/check_test_batch.py 'D:\工程\钣金导入\batch-NEW.json' --out 'D:\工程\钣金导入\batch-summary-NEW.json'
```

检查器退出码 0 为记录及本地字节一致；3 为需复核。consistent 不等于独立观察过 CAD，更不等于机械工程验收。任一失败、缺件、exit139、未知会话、原生读回缺失，均不得跳过原有安全门槛。不得上传客户 CAD 或含坐标的原始日志到公开仓库。

最终统一交回：完整 SHA、每轨测试数量、batch-summary、原始回执位置及真实错误。集中修复下一批，不为每个小改动重新派单。
