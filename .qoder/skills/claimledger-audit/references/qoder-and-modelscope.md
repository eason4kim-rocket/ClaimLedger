# 宿主集成与 ModelScope 验证

优先使用当前宿主实际具备的本地命令执行能力。QwenWork 中读取本 Skill 后运行 CLI，等待任务实际完成，再输出中文简报；不假设存在 Qoder Widget。宿主名称、版本与调用成功须分别实测，QwenWork 与 WorkBuddy 不是同一个产品。云端对话不等于本地离线运行；私有内容未经披露授权不得返回云端宿主。

以下 Qoder 指南仅在用户实际使用该宿主时适用，保留为兼容路径，并非必需安装项。

将本目录放在 `.qoder/skills/claimledger-audit`。启动新的 Qoder 会话或执行 `/skills reload`，在 `/skills` 中确认可发现，然后分别测试 `/claimledger-audit` 和自然语言请求，例如“审计这份报告是否有原始证据支持”。

## 中文可信交付台

审计完成后先运行：

```text
python scripts/claimledger.py brief JOB_ID --top 5 --json
```

优先通过 Qoder 的 `genui/show_widget` 使用 `assets/ui/claimledger-brief.html`：`widget_path` 传该相对路径，`data` 直接传入 `brief` 命令返回的 JSON 对象。Qoder 会将 `data` 注入 `window.__WIDGET_DATA__`；模板同时兼容旧变量名 `window.CLAIMLEDGER_BRIEF` 和内置空态数据。该文件是可移植、自包含的 HTML Widget 模板，不直接访问数据库、模型、原始文件或带令牌接口。

按钮只使用 `window.sendToAgent` 发送可读的中文意图。驳回、修正、豁免等动作必须由 Agent 复述内容和影响，取得明确确认后再调用 CLI 或本地 API。Widget 无法渲染时，以相同字段生成中文 Markdown 简报，完整证据审阅仍在 localhost 页面完成。

验证时至少覆盖：

- 卡片显示“自动审计—人工复核—可信交付”三阶段；
- 重要发现按未解决高风险优先；
- 组件源码不含令牌、绝对路径、证据全文和远程资源；
- 点击按钮不会直接提交专业决定；
- 重新执行 `brief` 后指标和解决状态同步更新。

发布到 ModelScope 时，ZIP 根目录必须直接包含 `SKILL.md`。打包源码、脚本、参考资料、资源、测试、许可证和依赖元数据；排除模型权重、虚拟环境、缓存、任务数据和私有文档。Skill 标签使用 `AI PC`，配套技术文章使用 `Intel AI PC`。
