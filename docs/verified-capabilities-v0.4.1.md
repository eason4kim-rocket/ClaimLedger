# ClaimLedger v0.4.1 已实测能力清单

## 可以明确声称

- 一句话触发后默认使用 Lite，并按采购、运营、咨询自动选择规则包；无法判断时使用 `generic-zh`。
- 本地审计 DOCX 成稿中的数字、日期、单位、主体、品类、期间和关键结论。
- 读取 DOCX、XLSX、PDF、PNG、JPG、TIFF；PDF 文本层优先，仅无文本页和图片触发 OCR。
- PP-OCRv5 Mobile 在 Apple M3 CPU 实际推理成功，模型安装后可断网运行。
- 生成原生 Word 批注、Excel 证据台账、审计 JSON、哈希 Manifest。
- 证据定位到 PDF 页/坐标、DOCX 段落/表格、XLSX 工作表/单元格。
- 复核页显示三阶段状态、剩余高风险数量和受令牌保护的产物下载入口。
- 高风险未处理时前后端都阻止最终稿；替换结论必须重新核证。
- 下载接口拒绝无令牌、错误令牌、错误任务、非白名单 kind、路径穿越、哈希变化和未生成的最终稿。
- 历史先例只给建议，不预选、不自动提交人工决定。
- 采购、运营、咨询共 100 条黄金结论的 Lite 全量基准：风险 Precision 100%、Recall 97.96%，严格证据 Top-5 召回率 91%。
- WPS Office Mac 12.1.26026 实际打开三案 DOCX 和 XLSX，无修复警告，批注、中文、筛选、冻结窗格和状态颜色可用。
- 77 项自动化测试通过；socket 守卫下 Lite 文本层审计的非回环连接尝试为 0。
- 最终 Skill ZIP 使用文件白名单，不含模型、缓存、数据库、令牌、用户材料和开发机绝对路径。
- Balanced 三结论离线闭环及 Embedding/Reranker 独立推理曾在 Apple M3 OpenVINO CPU 上通过；本轮没有重跑 8B。

## 不能声称

- Intel CPU、GPU、NPU 或 CPU fallback 已实测。
- Apple M3 上三行业 Balanced 全量已完成。
- 普通自然语言审计会自动启用 Balanced。
- Microsoft Word 或 Pages 已通过本轮兼容认证。
- 真人已完成本轮运营案例的 11 项高风险决定。
- 第二位审阅者盲标、真实客户背书或真实生产节时 70% 已完成。
- 自动联网补证、外部事实搜索、通用 RAG、通用 OCR、标书逐条合规或未经确认的自动改稿。
- 无证据结论可被记忆、拒绝先例或豁免提升为 `supported`。
