# 本地模型运行说明

`lite` 是生产默认模式；`deterministic` 跳过 OCR，仅用于无依赖测试；`balanced` 是必须明确选择的增强模式，绝不自动启用。

| 使用条件 | 组件 | 作用 |
|---|---|---|
| 默认，仅扫描件或图片触发 | PP-OCRv5 Mobile | 只识别没有可用文本层的页面，并按文件、页码和模型哈希缓存 |
| Balanced 可选生成模型 | OpenVINO/Qwen3-8B-int4-ov | 拆分复杂结论；只能依据已有证据编号判断支持关系 |
| Balanced 可选检索模型 | OpenVINO/Qwen3-Embedding-0.6B-fp16-ov | 召回语义相关的候选证据 |
| Balanced 可选排序模型 | OpenVINO/Qwen3-Reranker-0.6B-seq-cls-fp16-ov | 对候选证据重新排序，不得虚构引用 |

Lite 使用 PP-OCRv5 Mobile、词法检索和确定性核对，不需要 8B、Embedding 或 Reranker。模型权重不进入 Skill ZIP；只有安装模型时允许联网。

按顺序执行 `models status`、明确的 `models install --execute` 和 `models verify`。普通审计不得偷偷下载；模型缺失时必须清楚报错。

Balanced 使用 ClaimLedger 自带的本地模型网关 `http://127.0.0.1:8877/v3`。该网关：

- 只接受 `assets/models.yaml` 白名单内的模型编号；
- 使用独立访问令牌；
- 拒绝非本机监听地址；
- 在加载 Embedding 前释放 8B 生成模型；
- 预计算结论和证据向量，释放 Embedding 后再加载 Reranker；
- 记录实际 OpenVINO 设备和各阶段加载耗时。

Mac 默认使用 CPU。Intel 可使用 `AUTO`，只有 OpenVINO 实际识别到 GPU 时才会启用。没有实测不得宣称完成 GPU 验证。`CLAIMLEDGER_MODEL_GATEWAY_URL` 只能指向本机 HTTP 网关；拒绝 HTTPS 和非回环地址。旧变量 `CLAIMLEDGER_OVMS_URL` 仅用于兼容 v0.3。

Mac CPU 首个生成结果可能需要数分钟。本机请求默认超时为 1800 秒，可通过 `CLAIMLEDGER_MODEL_TIMEOUT_SECONDS` 调整。Balanced 超时必须明确失败，绝不能把 Lite 结果冒充 Balanced。

Apple M3 24GB 实测中，Balanced 网关峰值常驻内存达到 17,459,937,280 字节，较大任务会明显影响电脑使用。该数据只代表资源风险，不代表完整容量。当前验证边界是 3 条结论的 CPU 端到端闭环，以及独立的 Embedding 和 Reranker 推理；不得宣称已经完成 28/44 条结论的 Balanced 全案例验证。

模型权重始终放在 Skill ZIP 之外，并保留下载 revision 与 `installation.json`。模型失败时不得静默回退后继续保留 `balanced` 标签。
