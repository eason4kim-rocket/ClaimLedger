# Security Policy

## Supported versions

当前维护 `0.5.x`。安全修复会优先合入 `main`，必要时发布补丁版本。

## Reporting a vulnerability

请使用 GitHub 的私密漏洞报告入口：

<https://github.com/eason4kim-rocket/ClaimLedger/security/advisories/new>

不要在公开 Issue、讨论区或 Pull Request 中提交以下内容：

- 真实报告或证据文件；
- 提取后的敏感原文；
- API Token、Cookie、数据库或日志；
- 能直接识别个人、客户或供应商的信息；
- 未公开漏洞的完整利用步骤。

报告请尽量包括受影响版本、操作系统、最小复现、预期行为和实际行为。请使用合成数据替代真实业务材料。

## Security model

ClaimLedger 的默认安全边界是本地、封闭证据集：

- 审阅服务和本地模型网关只允许监听 `127.0.0.1` 或 `localhost`；
- 令牌在本机运行目录生成，不应写入源码或提交 Git；
- 原始报告和证据文件不得被覆盖；
- 导出前重新检查来源哈希和交付门禁；
- 模型输出不得直接创造证据定位或代替专业人员作决定；
- 可选模型下载属于显式操作，不是审计请求的隐含授权。

以下风险尤其值得报告：鉴权绕过、任意文件读取或写入、路径穿越、非本机监听、令牌泄露、哈希校验绕过、未授权最终稿导出，以及文档内容导致的命令或提示注入。

