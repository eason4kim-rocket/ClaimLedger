---
name: claimledger-audit
description: 对 AI 生成或人工起草的 DOCX 业务报告执行交付前本地证据审计。适用于采购与供应商评估、运营月报和 KPI 报告、行业研究、咨询交付、尽调备忘录及方案事实核证。用户提出“审计报告、核对原始证据、检查数字和口径、报告交付前审查、生成结论证据台账、本地或离线审稿、按岗位口径复核”等请求时使用。针对 PDF、DOCX、XLSX、PNG、JPG、TIFF 证据识别无来源、弱支持、来源冲突、过期、数值、日期、单位、主体、地区、含税口径和统计范围问题；要求人工确认后输出带批注 Word、证据台账、审计轨迹、产物清单和最终 DOCX。不用于通用 OCR、标书逐条合规比对、RAG 问答、隐私扫描、报告写作、文档总结或联网事实核查。
---

# ClaimLedger 报告证据审计

AI 写完以后，谁来证明它可以交付？

ClaimLedger 在本机读取一份已经成稿的 DOCX 报告，以及 PDF、DOCX、XLSX、PNG、JPG 或 TIFF 证据材料；逐条核证数字、日期、主体、单位、统计口径、来源冲突和过期表述；由人工确认专业决定后，生成可追溯的正式交付包。

输入：待审报告和本地证据文件夹。

核证：定位报告结论，回到原文件、页码、段落、单元格或 OCR 坐标核对。

复核：重要发现必须由人明确选择驳回、修正并复验或正式豁免。

交付：带批注 Word、Excel 证据台账、审计 JSON、产物清单和最终 DOCX。

例如，运营月报写“履约率 98.6%”，来源表实际为“96.8%”；ClaimLedger 会同时指出数字差异、Excel 单元格和建议动作，而不是只给出“可能有误”。

随附合成黄金集包含 100 条结论和 49 个植入风险，实测风险 Recall 97.96%、Precision 100%、证据 Top-5 召回率 91%。这些是脱敏重构的合成测试结果，不是真实客户数据或效果承诺。

始终保持原报告和全部证据文件不变，材料、推理、人工决定和导出均在本机完成。

## 判断是否适用

1. 当用户提供 `.docx` 待审报告和本地证据文件夹，并要求核证结论、追溯来源、识别冲突或完成交付确认时，使用本 Skill。
2. 若用户要求逐条比较招标要求与投标响应，或生成技术偏离表，说明该任务属于招投标合规审查。只有在用户需要用合同、证书、检测报告等材料核证方案中的事实承诺时，才继续使用 ClaimLedger。
3. 不要把写作、总结、隐私检查或联网事实核查转换成报告审计。ClaimLedger 只核对用户提供的封闭证据集。
4. 采购和供应商决策选择 `procurement-zh`；运营月报、KPI 和服务报告选择 `operations-zh`；行业研究和咨询交付选择 `consulting-zh`。无法可靠判断时直接使用 `generic-zh`，不要打断用户。`lithium-demo` 只用于随附回归案例。边界不清楚时读取 `references/use-cases.md`。
5. 区分运行模式和审阅配置。普通自然语言审计一律使用 `lite`。审阅配置是可选的个人记忆设置，不能替代运行模式。例如，运营月报应使用运行模式 `lite` 加规则包 `operations-zh`；只有用户明确要求记住审阅偏好时，才选择 `operations` 岗位模板。

## 执行审计

1. 将 `SKILL_DIR` 解析为本文件所在目录。所有命令均以 `SKILL_DIR` 为工作目录，不要假设用户项目根目录包含运行环境。
2. 确认待审报告是本地 `.docx`，证据路径是本地文件夹。不得使用网址代替证据包。
3. 检查 `SKILL_DIR/.venv`。如果不存在，只有在用户允许安装或下载后才能运行 `python scripts/bootstrap.py`。单纯提出查看、诊断或审计，不代表允许安装。环境已安装时，代替用户执行后续本地命令，不要要求用户复制命令。
4. 运行 `python scripts/claimledger.py doctor --json`。若缺少必要依赖、服务不是仅监听本机、磁盘不足、输入加密或证据不可读，立即停止并用中文给出唯一、明确的修复动作。
5. 运行 `python scripts/claimledger.py models status --profile lite --json`。如果用户已经允许下载 OCR/本地模型且资源缺失，运行 `python scripts/claimledger.py models install --profile lite --execute --json`，随后运行模型验证。不带 `--execute` 的安装命令只做检查，不会下载。
6. 用户要求启用本地审阅记忆时，创建或选择命名配置，并从 `generic`、`audit`、`operations`、`consulting` 中选择岗位模板。读取 `references/review-memory.md`。没有人工明确指令和理由时，不得创建、提升、激活或停用策略。
7. 普通审计使用 `lite` 并自动打开复核页面：

   ```text
   python scripts/claimledger.py audit --report REPORT.docx --sources SOURCE_DIR --case-name NAME --rule-pack RULE_PACK --profile lite --as-of-date YYYY-MM-DD [--review-profile NAME] --open --json
   ```

   `deterministic` 仅用于测试或紧急无 OCR 回退。不得因为报告复杂就选择 `balanced`。用户在提问、比较或粘贴材料时提到 Balanced，不代表同意启用。只有用户明确说“启用 Balanced”等指令，并且模型状态与验证均通过时才可使用。普通审计始终默认 `lite`。Balanced 可能使 24GB Mac 明显卡顿，只能启动 ClaimLedger 自带的鉴权本地模型网关，绝不能切换到云端。
8. 使用 `--no-serve` 审计时，另行运行 `python scripts/claimledger.py serve --daemon --port 8765 --json` 启动复核服务。服务只能监听 `127.0.0.1` 或 `localhost`。
9. 自动审计结束后，不要只返回复核链接。运行 `python scripts/claimledger.py brief JOB_ID --top 5 --json` 获取稳定、脱敏的中文简报。人工决定前统一称为“候选发现”。除非用户询问，不主动暴露模型或命令行编排细节。
10. 优先通过 Qoder `genui/show_widget` 使用 `assets/ui/claimledger-brief.html`：`widget_path` 传该相对路径，`data` 直接传入 `brief` 命令返回的 JSON 对象。Qoder 会将 `data` 注入 `window.__WIDGET_DATA__`；不要只加载模板而省略 `data`，也不要把 JSON 拼进聊天文本。组件不得读取数据库、模型、令牌或原始文件；按钮只能通过 `sendToAgent` 发送人类可读的中文意图，不能直接写入决定。模板无法渲染时，退化为结构相同的中文 Markdown 简报，不得静默省略结果。
11. 简报解释优先级最高的 3–5 条候选发现。每条使用“报告原结论—证据怎么说—具体差异—建议动作”的通俗结构，保留必要的数字、日期、单位、主体和证据位置；不要只展示 `partial`、`conflict`、问题代码或证据编号等内部术语。结尾主动询问一次：“需要我继续帮你处理吗？我可以逐条解释、先处理高风险，或按你的明确选择执行修改、驳回或豁免。”不要把打开网页作为唯一下一步。
12. 用户要求继续时，在当前 Qoder 会话中充当复核助手。支持“解释第 N 条”“先看高风险”“按建议修改第 N 条”“第 N 条是误报”“豁免第 N 条”“处理完后导出”等自然语言请求；根据当前任务重新读取状态，并调用 `decide`、`status` 和 `export` 完成操作，不要求用户复制 CLI 命令。
13. 可以提出推荐动作和替换文本，但执行 `reject`、`replace` 或 `waive` 前必须复述将要写入的决定、理由及影响，并取得用户明确确认。用户只说“你看着办”“全部处理”或“不想审核”时，先给出分组建议，不得自动提交专业责任决定。批量执行只允许处理用户明确确认的同一组发现。
14. 引导用户进入本机复核页面作为可视化核验和人工决定的另一入口，而非强制入口。每个交付阻断项必须明确选择确认发现、驳回误报、修正并复验或正式豁免。不得代替用户作出专业责任决定。“确认发现”只表示认可风险存在，不会解除高风险阻断。
15. 使用用户明确提供的姓名或岗位作为操作人；未提供时记录为“当前用户确认、Qoder 代执行”，不得冒充用户亲自点击，也不得写入无关的开发或对话工具名称。
16. 历史先例只能作为建议。豁免不能成为事实；驳回误报必须高度匹配原问题范围；修正文案必须重新核证。只有人工激活的版本化策略才能影响后续新任务。
17. 复核完成后运行 `python scripts/claimledger.py status JOB_ID --json`。只有 `delivery_ready` 为 `true` 时才可导出最终稿：

   ```text
   python scripts/claimledger.py export JOB_ID --final --json
   ```

18. 返回新的最终 DOCX、带批注报告、证据台账、审计 JSON 和产物清单，并在 Qoder 中说明每个文件的中文用途。优先提供本地复核页面中受鉴权保护的下载按钮。不得声称原始报告已被修改。

## 演示工作流

用户询问能力但没有提供私有文件时，只生成随附的合成案例：

```text
python scripts/claimledger.py demo --scenario procurement|operations|consulting --output OUTPUT_DIR --json
```

完整展示 OCR 和异构文档时优先使用 `procurement`；展示 KPI、期间和分母核对时使用 `operations`；展示市场边界、情景、样本外推和政策强度时使用 `consulting`。明确说明案例均为基于公开问题重构的脱敏合成材料，不代表真实客户背书。

## 证据与决定规则

- 以报告结论为审计单位，不以搜索问题为单位。复合结论中的关键事实可以独立成立或失败时，应拆分审计。
- 模型只能从已有证据编号中提取结论、排序候选或判断支持关系。拒绝模型虚构的引文、文件名、位置和引用。
- 保留证据原文、SHA-256 和可复验位置：PDF 页码、Word 段落或表格单元格、Excel 工作表和单元格、OCR 坐标框。
- 核对全部关键限定条件，包括主体、品类、地区、期间、含税口径、币种、单位数量级、分母、样本量和时效性。数字相同不代表结论一定得到支持。
- 明确展示不同证据文件之间的冲突，不得悄悄选择更方便的来源。
- 低置信度 OCR 统一标记为 `needs_review`，并展示原图和坐标。
- 驳回误报和正式豁免必须填写理由；修正必须提供新文本。保留操作人、时间、原文和所选证据编号。
- 解释问题代码或调整交付风险级别前，读取 `references/audit-taxonomy.md`。

## 安全边界

- 服务只监听 `127.0.0.1` 或 `localhost`；推理、存储、复核和导出均在本机进行。
- 不得上传报告、证据、提取文字、日志或向量。
- 不得覆盖源文件；每次运行都写入新的任务目录。
- 对加密、损坏、超大、不支持或哈希变化的来源，明确停止或隔离处理。
- 除非用户明确要求，不在终端日志中输出证据全文。
- 自动审计完成不等于专业批准；人工决定日志属于正式交付物的一部分。

## 命令接口

命令、参数、内部状态枚举和文件格式名称属于稳定技术接口，保留英文：

```text
python scripts/claimledger.py doctor --json
python scripts/claimledger.py doctor --deep --json
python scripts/claimledger.py models status --profile lite|balanced --json
python scripts/claimledger.py models install --profile lite|balanced [--execute] --json
python scripts/claimledger.py models verify --profile lite|balanced --device CPU|GPU|AUTO --json
python scripts/claimledger.py models serve --host 127.0.0.1 --port 8877 --device CPU|GPU|AUTO
python scripts/claimledger.py profiles create NAME --role generic|audit|operations|consulting --json
python scripts/claimledger.py profiles list|show|export|import|delete ...
python scripts/claimledger.py memory list|prune --profile NAME --json
python scripts/claimledger.py policy draft --from-memory MEMORY_ID --reason REASON --json
python scripts/claimledger.py policy activate|retire POLICY_ID --reason REASON --json
python scripts/claimledger.py serve --host 127.0.0.1 --port 8765 [--daemon] --json
python scripts/claimledger.py audit --report REPORT.docx --sources SOURCE_DIR --case-name NAME --rule-pack generic-zh|procurement-zh|operations-zh|consulting-zh|lithium-demo --profile lite|deterministic|balanced --as-of-date YYYY-MM-DD [--review-profile NAME] [--no-serve] [--open] --json
python scripts/claimledger.py status JOB_ID --json
python scripts/claimledger.py brief JOB_ID --top 5 --json
python scripts/claimledger.py decide JOB_ID FINDING_ID --action accept|reject|replace|waive [--replacement TEXT] [--reason TEXT] [--evidence-id EVIDENCE_ID] [--actor ACTOR] [--risk-owner OWNER] [--waiver-expires-at YYYY-MM-DD] --json
python scripts/claimledger.py export JOB_ID --annotated --ledger --json
python scripts/claimledger.py export JOB_ID --final --json
python scripts/claimledger.py benchmark --dataset LABELS.json --json
python scripts/claimledger.py demo --scenario procurement|operations|consulting|golden-v2 --output OUTPUT_DIR --json
```

## 按需读取的参考资料

- `references/use-cases.md`：选择适用的职业工作流，并避开招投标逐条合规赛道。
- `references/audit-taxonomy.md`：解释审计状态、问题代码、风险级别和交付条件。
- `references/statuses.md`：解释审计状态与人工决定的区别。
- `references/rules.md`：新增或修改 YAML 规则包。
- `references/model-runtime.md`：启用模型增强模式。
- `references/review-memory.md`：使用审阅配置、历史先例和版本化策略。
- `references/qoder-and-modelscope.md`：验证和打包发布。
