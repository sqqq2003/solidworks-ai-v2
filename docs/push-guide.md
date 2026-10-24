# 推送指南（本机网络连不上 GitHub 时）

## 现状诊断（2026-10-24）

本机到 GitHub 的连接被硬屏蔽，**不是 git 配置问题**：

| 测试 | 结果 |
|------|------|
| `nslookup github.com` | 解析到 `127.0.0.1` / `::1`（DNS 被污染） |
| `curl https://github.com`（走沙箱代理） | SSL 错误 35 |
| `curl --resolve github.com:443:140.82.121.4`（指定真实 IP） | 仍然 SSL 错误 35 → 代理层屏蔽，改 DNS 也没用 |
| `curl https://pypi.org` / `https://gitee.com` | 200 → 代理只放行白名单站点 |

因此 `git push origin` 在本沙箱内不可能成功；仓库本身完全健康：

- 分支 `wb/issue6-five-modules-framework`，HEAD=`5cf750f`，工作区干净
- 本地领先 `origin/main` 共 **51 个提交**（22 个是本轮 Issue #6 工作，29 个是以往未推送的）
- 自包含 bundle 已生成：`solidworks-ai-v2-wb-issue6.bundle`（完整历史，662 KB）

## 方案 A：在你自己终端推（推荐）

在**沙箱外**的 PowerShell 里（开了能访问 GitHub 的 VPN/代理后），仓库就在 `C:\sw-ai-v2-work`，直接：

```powershell
cd C:\sw-ai-v2-work
git push -u origin wb/issue6-five-modules-framework
```

首次推送会弹浏览器或要 PAT（GitHub 已不支持密码认证）。如果没有 VPN，用方案 B。

## 方案 B：用 bundle 中转（任意能上 GitHub 的机器）

1. 把 `solidworks-ai-v2-wb-issue6.bundle` 拷到目标机器
2. 在已有克隆里（或先 `git clone https://github.com/sqqq2003/solidworks-ai-v2.git`）：

```bash
git fetch /path/to/solidworks-ai-v2-wb-issue6.bundle wb/issue6-five-modules-framework
git push origin FETCH_HEAD:wb/issue6-five-modules-framework
```

全新克隆的场景 bundle 自带完整历史，`git clone solidworks-ai-v2-wb-issue6.bundle` 也能直接得到仓库。

## 方案 C：镜像到 Gitee（国内可达，已实测 200）

Gitee 在本机网络可达。若要镜像：

1. 在 gitee.com 建**空仓库**（不要初始化 README）
2. 本沙箱内即可推送：

```bash
git remote add gitee https://gitee.com/<你的用户名>/<仓库名>.git
git push -u gitee wb/issue6-five-modules-framework
```

Gitee 推送同样需要账号密码/PAT，会在终端提示输入。

## 注意事项

- 推送会把 **51 个提交**一起推上去（含以往未推送的工作），这是预期行为。
- 提交作者目前是 `WorkBuddy <workbuddy@local>`。想换成你自己的身份：`git config user.name "你的名字"` + `git config user.email "你的邮箱"`（只影响以后的提交；历史提交要改需 filter-branch，会变所有 SHA，验收 JSON 里的 HEAD 也要同步更新）。
- 推送前先确认 GitHub 上该仓库的默认分支和保护规则，避免 CI（`.github/workflows/cloud-tests.yml`）对 51 个提交全量跑一遍造成意外。
