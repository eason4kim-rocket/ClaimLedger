# ClaimLedger v0.5.0 发布冻结验证

验证日期：2026-07-23

## 发布产物

| 产物 | 大小 | SHA-256 |
|---|---:|---|
| `claimledger-audit.zip` | 816,027 字节 | `c6565b741e767e9af079295aa97138f9447a871dce9ebb0c9bd387f8c094f3fa` |
| `claimledger-0.5.0-py3-none-any.whl` | 767,145 字节 | `96f58f0969cf7ae620535257943c209203fe196ea8774abbb4e78bbd637e3e46` |

- ZIP 共 64 个成员，根目录直接包含且仅包含一个 `SKILL.md`。
- `dist/modelscope-upload/` 由同一 ZIP 展开生成，可以直接拖入魔搭项目文件上传框。
- 上传目录不含模型、缓存、数据库、令牌、用户文档、绝对用户路径、`build/`、`egg-info` 或 `__pycache__`。
- 两次连续构建的 ZIP 与 wheel 大小和 SHA-256 完全一致。

## 自动化与结构验证

- 87 项自动化测试全部通过。
- `skill-creator/scripts/quick_validate.py` 对源码目录和最终 ZIP 解压目录均返回 `Skill is valid!`。
- 最终 ZIP 在全新临时目录解压，并在新建 Python 3.11 环境中以 `--no-deps --no-build-isolation` 成功安装为 `claimledger==0.5.0`。
- `dist/modelscope-upload/` 在另一新建 Python 3.11 环境中成功安装。
- 两种安装均复验了 wheel 内的中文 Widget 和 1024×1024 PNG 图标。

## v0.5.0 功能验证

- `claimledger brief JOB_ID --top 5 --json` 已加入稳定 CLI。
- 真实 Lite 运营案例生成 28 条候选发现、12 条风险发现和 11 条未处理高风险；中文简报正确显示阶段、覆盖状态、优先发现、差异、位置、建议动作和交付物状态。
- Qoder Widget 为单文件自包含 HTML，不含远程资源、令牌、绝对路径和完整证据正文；按钮只通过 `sendToAgent` 发送可读中文意图。
- 本地审阅页增加稳定发现锚点、品牌栏、本地离线标记、指标、风险分布、三阶段状态、交付闸门和五类下载入口。
- 驳回、修正、豁免和策略理由均改为页面内模态框；源码不再使用浏览器原生 `prompt()`。
- 修正模态框显示原文与建议文本，修正后仍必须重新核证；正式豁免要求理由和责任人。
- 360px、768px 和 1440px 宽度完成真实 HTML 渲染检查；亮色／暗色由系统主题自动适配。

## 黄金集回归

重新运行三行业 Lite 合成黄金集：

| 指标 | v0.5.0 |
|---|---:|
| 结论提取 Recall | 100% |
| 植入风险 Precision | 100% |
| 植入风险 Recall | 97.96% |
| 植入风险 F1 | 98.97% |
| 状态准确率 | 97% |
| 严格证据 Top-5 Recall | 91% |

机器结果：`docs/results/golden-v050.json`。

这些指标来自公开问题原型驱动、脱敏重构的合成黄金集，不是真实客户数据或效果承诺。

## 未扩大声明的边界

- 本轮没有重跑 Balanced 8B。
- Intel CPU/GPU 仍待实机验证。
- WPS 人工打开认证沿用 v0.4.1 已完成边界，本轮没有伪称重新人工验收。
- Qoder Widget 已按官方 Skill UI 机制准备并完成独立 HTML 渲染与消息协议测试；重新上传后的市场卡片和 Qoder 会话内模板注册仍需发布者在真实账号中做最后一次人工检查。
- 未执行魔搭上传、文章发布、视频录制或比赛报名。
