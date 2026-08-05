# ClaimLedger v0.4 已实测功能清单

## 可以明确声称

- 本地审计 DOCX 成稿中的数字、日期、单位、主体、品类、期间和关键结论。
- 读取 DOCX、XLSX、PDF、PNG、JPG、TIFF 证据；PDF 文本层优先，无文本页才 OCR。
- PaddleOCR PP-OCRv5 Mobile 在 Apple M3 CPU 实际推理成功，模型安装后可离线运行。
- 生成原生 Word 批注、8 工作表 Excel 台账、审计 JSON 和哈希 Manifest。
- 证据定位到 PDF 页/坐标、DOCX 段落/表格、XLSX 工作表/单元格。
- 六种状态：`supported`、`partial`、`unsupported`、`conflict`、`stale`、`needs_review`。
- 高风险人工门禁、替换后重新审计、豁免范围/到期/复核、append-only 决定日志。
- 个人审阅配置、四类岗位模板、相似历史先例、版本化策略和任务快照。
- 历史先例只给建议，不自动接受、驳回、替换、豁免或放行。
- 双人盲标工作簿导出/导入与一致率、Precision、Recall、F1、分歧清单计算。
- 内置 localhost OpenVINO 网关、独立令牌、模型白名单和阶段释放。
- Balanced 三模型在 Apple M3 CPU 完成三结论离线闭环；Embedding/Reranker 独立实推通过。
- 采购、运营、咨询 100 条黄金结论的 Lite 全量基准。
- Python 3.11/3.12 核心干净安装、73 项测试和 deterministic 运营审计。

## 不能声称

- Intel GPU、NPU 或 CPU fallback 已实测。
- Apple M3 上 28/44 条全案例 Balanced 已完成。
- Microsoft Word 或 Pages 已通过兼容认证。
- 真实客户材料、客户背书或真实生产节省 70%。
- 自动联网补证、外部事实搜索、通用 RAG、通用 OCR、标书逐条合规或自动改稿。
- 无证据结论可被记忆或豁免提升为 `supported`。
- 未经人工处理高风险即可生成最终交付稿。
