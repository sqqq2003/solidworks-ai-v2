# 示例报告说明（真实实测，非手编）

`verify_report_example.json` / `verify_report_example.md` 是用本包
CLI 对一份从当前 dev 重建的检出实测跑出的报告：

- 检出来源：dev/cloud-ai @ 243e269f（动手时实查的 HEAD）。
- 重建方式：因云端无 git 克隆条件，检出由连接器逐文件拉取
  dev 的 tests/ 在场套件、csharp-bridge 测试与客户端、以及
  src/ 导入闭包拼成（非完整 git clone；JSON 里的 root 字段是
  本地重建目录路径）。数字全部是该次实测数，非手编。
- 实测结果：13 套件中 9 个在场全部通过（94/94 用例），
  4 个缺失（#32/#35/#36/#37 分支未合并，预期状态），
  1 项基线差异：recovery-guards 实测 8 项、基线期望 7 项——
  #30 分支版实测为 7 项，dev 在 #30 合并后又加了 1 项，
  属基线漂移，按纪律本批不改基线，只标 diff，待归属方确认后
  随其 PR 更新基线。
- 退出码 1：原因正是上述 1 项基线差异 + 4 个缺失套件
  （未加 --allow-missing）。

`WINDOWS_ACCEPTANCE_PACK.md` 是 `windows-pack` 命令的真实输出
（42 项总表），与代码里的 windows_pack.py 数据一一对应。
