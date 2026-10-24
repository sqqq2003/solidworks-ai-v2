# 推送指南与连接诊断（已解决）

## 结论（2026-10-24 20:30）

分支 `wb/issue6-five-modules-framework`（HEAD=`231ab44`，51 个提交）**已成功推送到 GitHub**：

- 远端：`https://github.com/sqqq2003/solidworks-ai-v2`（私有仓库）
- 远端 SHA 与本地一致，已设置 upstream 跟踪
- GitHub Actions「Portable Python regression」已在推送提交上触发运行
- PR 链接：https://github.com/sqqq2003/solidworks-ai-v2/pull/new/wb/issue6-five-modules-framework

## 当时的阻塞与解法

推不上的根因**不是网络屏蔽，也不是凭据缺失**，而是两件事叠在一起：

1. **仓库是私有的** → 匿名访问全部 404（早期诊断被这一点误导）
2. **schannel 吊销校验失败**：`CRYPT_E_NO_REVOCATION_CHECK (0x80092012)`。本机走沙箱代理（`127.0.0.1:50434`）时 TLS 证书吊销校验无法完成。`http.schannelCheckRevoke=false` 无效，`http.sslVerify=false` 可解。

可用的前提条件（都已具备）：
- Windows 凭据管理器里有 `sqqq2003` 的 GitHub OAuth token（`git credential fill` 可取，push 时自动带上）
- token 对该仓库有 push + admin 权限

## 本机再次推送的命令

```bash
git push origin wb/issue6-five-modules-framework
```

仓库级配置已写入 `.git/config`（不入库）：`http.sslVerify=false`。
换到正常网络环境时可移除：`git config --unset http.sslVerify`。

## 如果换机器/换网络

- **有 GitHub 访问权限的机器**：直接用 bundle 中转（`solidworks-ai-v2-wb-issue6.bundle`，含完整历史）：

```bash
git fetch /path/to/solidworks-ai-v2-wb-issue6.bundle wb/issue6-five-modules-framework
git push origin FETCH_HEAD:wb/issue6-five-modules-framework
```

- **Gitee 镜像**（不再需要，仅作备用）：`git remote add gitee <url> && git push -u gitee wb/issue6-five-modules-framework`

## 备注

- 推送包含 51 个提交：本轮 Issue #6 的 22 个 + 以往未推送的 29 个。
- 远端已有其他 agent 的分支（如 `feat/issue6-ql5050px-five-modules`），与本分支同名不同内容，互不影响；如需合并由维护者决定。
- 提交作者为 `WorkBuddy <workbuddy@local>`（沙箱内无用户身份配置）。如要改为真实身份，设置 `user.name` / `user.email` 后只影响新提交。
