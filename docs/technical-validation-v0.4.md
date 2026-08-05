# ClaimLedger v0.4 技术验证报告

> 只记录 2026-07-19 已实际运行的能力。ModelScope 发布、比赛报名、客户背书、双人盲标、Intel GPU 和 Word/Pages 兼容性不在本报告中伪造完成状态。

## 1. 验证环境

| 项目 | 实测值 |
|---|---|
| 设备 | MacBook Air，Apple M3，8 核，24 GB |
| 系统 | macOS 15.7.7，arm64 |
| 完整本地 AI Python | 3.11 |
| PaddlePaddle / PaddleOCR | 3.3.1 / 3.7.0 |
| OpenVINO / OpenVINO GenAI | 2026.2.1 / 2026.2.1 |
| OpenVINO 可用设备 | `CPU` |
| Intel GPU | 未检测、未实测 |

## 2. Lite 与 PaddleOCR

`models verify --profile lite --device CPU` 已完成 PP-OCRv5 Mobile 的实际图片推理，而不只是检查包是否安装。本机缓存包含：

- `PP-LCNet_x1_0_doc_ori`
- `PP-LCNet_x1_0_textline_ori`
- `PP-OCRv5_mobile_det`
- `PP-OCRv5_mobile_rec`

三行业 fresh-task 基准均使用 `lite`，且模型安装完成后运行过程中没有下载权重：

| 案例 | 结论 | 植入风险 | 总耗时 | 结果 |
|---|---:|---:|---:|---|
| 采购与供应商评估 | 44 | 23 | 51,841 ms | 覆盖完整 |
| 运营月报 | 28 | 12 | 770 ms | 覆盖完整 |
| 咨询市场研究 | 28 | 14 | 901 ms | 覆盖完整 |

采购案例包含扫描 PDF、TIFF、JPG 和银行回单，因此 OCR 占主要耗时。运营和咨询材料存在文本层，系统没有为了展示 OCR 而重复识别。

跨行业总指标：

- 结论提取 Precision / Recall / F1：100% / 100% / 100%。
- 风险识别 Precision / Recall / F1：100% / 97.96% / 98.97%。
- 严格证据 Top-5 召回率：91%。
- 高风险召回率：87.80%。
- Issue-code Micro F1：79.25%；Macro F1：80%。
- 进程峰值 RSS：2,959,769,600 bytes。

机器可读明细：`docs/results/golden-v04.json`。

## 3. Balanced 本地模型

三个模型由显式安装命令下载，普通审计不会触发下载。安装清单保存 snapshot revision、文件大小与 SHA-256：

| 角色 | 模型 | revision |
|---|---|---|
| 关键结论抽取 | `OpenVINO/Qwen3-8B-int4-ov` | `5c47abf4b8e12ebe8e99745bb0c1ec17e0c0abcc` |
| 证据向量 | `OpenVINO/Qwen3-Embedding-0.6B-fp16-ov` | `82a0035040926a5c0dcf251209218e096c5eeb1c` |
| 候选排序 | `OpenVINO/Qwen3-Reranker-0.6B-seq-cls-fp16-ov` | `4b0e5e6594de720a793646c0af2cfd52f8a45fa6` |

`models verify --profile balanced --device CPU` 已逐文件复验大小与 SHA-256，并完成 Embedding 与 Reranker 实际推理。

三结论 Balanced 离线短案例已跑通完整阶段：

- 8B INT4 关键结论抽取；
- 显式释放生成模型；
- Embedding 批量向量；
- 显式释放 Embedding；
- Reranker 候选排序；
- 标准 Word、Excel、JSON 和 Manifest；
- 无人工决定时 `delivery_report.docx` 被正确阻止；
- 临时 localhost 网关在任务结束后自动退出。

首次成功运行总耗时 528,705 ms，其中 generation load 400,900 ms、Embedding load 2,080 ms、Reranker load 1,916 ms；模型网关峰值 RSS 15,307,571,200 bytes。第一次尝试在 180 秒旧超时下明确失败，未静默降级 Lite；修复后默认模型请求超时为 1,800 秒。

增加 OpenVINO 编译缓存、Qwen3 非思考 chat template 和 JSON 完成即停止生成后，首次缓存写入总耗时 556,554 ms；下一次缓存命中总耗时 427,015 ms，其中 generation load 350,555 ms，模型网关峰值 RSS 17,459,937,280 bytes。缓存会额外占用约 6.4 GB 磁盘，因此 `doctor --deep` 必须继续报告磁盘空间，模型和编译缓存均不进入 Skill ZIP。

结论：Balanced 在 M3 24 GB CPU 上可运行，但首次加载慢且峰值内存显著高于 Lite，不应作为 Mac 日常默认。Intel GPU 未实测，不能宣称已验证。

28 条运营报告的 Balanced 全量复验启动后造成明显的桌面响应下降，运行 5 分 38 秒时按用户要求主动终止并确认临时网关完全退出；这次运行没有产出结果，不计为通过或失败。v0.4 的已验证 Balanced 边界因此是“三结论完整闭环 + Embedding/Reranker 独立实推”，不是三行业 Balanced 全量。比赛演示和日常使用应默认 `lite`。

## 4. 审阅记忆与策略治理

已完成并测试：

- `generic`、`audit`、`operations`、`consulting` 岗位模板。
- 本地个人配置、365 天最小化先例、最多三条相似历史匹配及匹配原因。
- `accept`、`reject`、`replace`、`waive` 的差异化记忆语义。
- `waive` 永远不能形成支持证据或策略。
- 策略必须经过草稿、显式激活、停用；激活只影响新任务。
- 任务冻结岗位版本、策略版本/哈希、记忆快照哈希。
- 两个配置的记忆完全隔离，删除配置后策略不可调用。
- 记忆命中只显示建议，不自动勾选任何人工决定。

真实 smoke 测试中，运营岗位配置在第二个任务命中历史先例，但原 `conflict` 状态和未处理高风险数量均未被自动改变。

## 5. 文档与表格交付 QA

三套案例均生成：

- `annotated_report.docx`
- `claim_ledger.xlsx`
- `audit.json`
- `artifact_manifest.json`

`delivery_report.docx` 只在真实人工处理全部高风险后生成。黄金标签不是人工交付决定，评测器不会把标签偷偷写成 `reject`、`replace` 或 `waive`。

DOCX 检查：

- 采购 44、运营 28、咨询 28 个 `commentRangeStart`、`commentRangeEnd`、`commentReference` 和 comment body 数量完全配对。
- ZIP 包和 XML 结构检查通过。
- LibreOffice 可打开并提取全部文本；打包版 LibreOffice 不读取 macOS 系统中文字体，因此其 PNG 出现方框，不能用来判断真实字体。
- macOS Quick Look 三案原生预览均成功，中文、层级和版式正常。
- Pages 的 AppleScript 自动导入对最简 DOCX 也失败，因此不记录为有效 Pages 兼容测试；Microsoft Word 未安装、未实测。

XLSX 使用 `artifact-tool` 2.8.24 导入并渲染三案全部 8 个工作表，共 24 个工作表；公式错误扫描为 0。已检查概览、结论台账、风险行动、计算检查、证据候选、决定日志、文件清单和审计配置。最大表为采购证据候选 `A1:M2226`。

盲标技术支持已生成三套不含系统预测标签的工作簿；导入、分歧清单、一致率、Precision、Recall 和 F1 由自动化测试覆盖。第二位人工审阅者尚未提供，不把单人金标冒充双人盲标。

## 6. 自动化、安全与 Skill

- 73 项自动化测试全部通过。
- 最终 ZIP 在全新 Python 3.11 和 Python 3.12 核心环境分别完成 73 项测试、`pip check` 和 28 条运营 deterministic 审计。
- Python 3.11 已验证完整 `local-ai`；Python 3.12 本轮只声称核心/deterministic 兼容，不声称 PaddleOCR 或 OpenVINO 完整环境。
- SQLite `schema_version=2` 向前迁移，v0.3 任务保持可读。
- API、模型网关、服务和文件预览均限制 loopback 与随机令牌。
- 临时模型网关在原生推理不响应优雅停止时，5 秒后强制清理其精确 PID。
- 模型缺失、哈希异常、认证失败和 Balanced 超时都明确失败。
- 最终稿仍要求全部高风险项有人工决定。
- `quick_validate.py` 通过。
- Skill 触发描述明确排除通用 OCR、RAG、联网事实搜索、标书逐条合规、文档总结和未确认自动改稿。

## 7. 尚未声称完成

- Intel AI PC CPU/GPU/CPU fallback 实测。
- Microsoft Word 与 Qoder GUI `/skills reload` 的本机最终人工点击复验。
- 物理关闭 Wi-Fi；当前是模型安装完成后的 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 和受限网络环境运行。
- 第二位审阅者盲标。
- 真实客户节省 70% 审稿时间的生产测量。
- ModelScope 上传、文章、视频和比赛报名。

这些项目不影响 v0.4 技术包构建，但发布材料必须继续标注“待验证”。
