# ClaimLedger v0.4.1 发布冻结记录

冻结日期：2026-07-19

## 构建物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `claimledger-audit.zip` | 147,389 bytes | `3001c12c139564c3cbbcc852bfb1dcff44fdb7eb16fcb389f00d450912b01ea1` |
| `claimledger-0.4.1-py3-none-any.whl` | 105,240 bytes | `3b3d00d5654637f4b6679dcaabadca2bd772d7b50ca5aa8ecadb12e445c4a2c5` |

Skill ZIP：

- 根目录直接包含 `SKILL.md`。
- 58 个成员。
- 两次独立构建逐字节一致。
- 使用白名单打包并复验包内 manifest。
- 不含模型、缓存、虚拟环境、数据库、令牌、用户材料和开发机绝对路径。

wheel：

- 两份独立临时源码树在相同 `SOURCE_DATE_EPOCH` 下构建。
- 两次 wheel 逐字节一致。

## 干净环境

全新 Python 3.11.12 venv：

- 从最终 wheel 安装 `claimledger==0.4.1`。
- `pip check`：无损坏依赖。
- 从最终 ZIP 解压后运行 `quick_validate.py`：通过。
- 从最终 ZIP 运行 77 项测试：全部通过。
- installed `doctor`：核心依赖通过；可选 Paddle/OpenVINO 未安装时被准确报告为未就绪。
- installed deterministic 运营审计：28 条结论、11 项高风险、覆盖完整；最终稿被人工门禁阻止。

## 离线与网络边界

`test_offline.py` 在测试进程安装 socket 守卫，只允许 loopback。一次 Lite 文本层审计完成，非回环连接尝试为 0。该测试不冒充“物理关闭 Wi-Fi”，但可证明正常审计代码路径没有外联。

## GUI 验证

- Chrome：本地复核页、三阶段状态、禁用的最终稿按钮和四个标准下载入口通过。
- WPS Office Mac 12.1.26026：三份带批注 DOCX、三份 Excel 台账通过，无文件修复警告。
- Qoder：全新会话能发现 ClaimLedger、运营规则包和能力边界。最终 Skill 明确把 runtime `lite` 与 reviewer-memory `operations` 分离。

## 未冻结为“已通过”

- 本轮真人 11 项风险决定。
- Intel CPU/GPU。
- Microsoft Word/Pages。
- Balanced 三行业全量。
- 第二位盲标与真实客户节时。
