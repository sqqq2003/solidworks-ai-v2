# Gork 统一交测

固定源码 pin：`d65b7c64e8318bdfcd217ccf7e1c36f78a1a2164`。本目录在后续仅添加了交测包和回执，生产代码未再变化；请按此源码pin检出或使用包内source.zip，不把回执提交误填成源码版本。

gork-test-kit.zip 是源码交测包，含 source.zip、候选哈希、矩阵、回传模板、源码索引和说明。不是 Windows 免安装运行时。解压后先校验 kit SHA256 `937e5367194d6f600dd5c4f2a94a82de8c42e419493c2f67cd7e6a8de9056edd`，source.zip SHA256 `fe6c686edea6b54852b792a718277f1911ba549e6ffc267ed91964c2528282ff`。

再将 source.zip 解压到新目录，运行 `python work/verify_test_handoff.py .`，安装 requirements-cloud.txt，运行 app.py。干净Windows发行环境按 docs/unified-candidate.md 重新构建便携包，不能覆盖用户旧目录。

1081项整合离线回归1058通过23跳过；桌面相关29项另在虚拟显示通过。新工作区方案/影响分析/具名审核/Windows副本执行与矩阵回传审核均已接通代码入口。实机仍not_run，所有原生/工程/制造放行需独立验收。不要中断原有测试pin。

下一批先验证环境/界面→旧窗口保留与新PID共存→DWG分析/计划→真实滚筒800→钣金/真实车件/装配运动干涉→图纸BOM引用与退出。填写submission模板并核对，缺证据保持review_required。一份证据PR回链统一验收Issue #46及本交付PR。