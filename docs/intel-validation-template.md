# Intel AI PC 验证模板

> 没有 Intel AI PC 时保留本模板，不填写推测值。执行前先确认模型已显式安装，且报告材料可用于本机测试。

## 环境记录

| 字段 | 实测值 |
|---|---|
| 日期 | |
| 设备型号 | |
| CPU | |
| GPU | |
| NPU | |
| 内存 | |
| 操作系统 | |
| Python | |
| OpenVINO | |
| OpenVINO GenAI | |
| GPU 驱动 | |
| generation revision | `5c47abf4b8e12ebe8e99745bb0c1ec17e0c0abcc` |
| embeddings revision | `82a0035040926a5c0dcf251209218e096c5eeb1c` |
| reranker revision | `4b0e5e6594de720a793646c0af2cfd52f8a45fa6` |

## 运行命令

```bash
claimledger doctor --deep
claimledger models status --profile balanced
claimledger models verify --profile balanced --device CPU
claimledger models verify --profile balanced --device GPU

claimledger audit \
  --report REPORT.docx \
  --sources EVIDENCE_DIR \
  --case-name intel-balanced-cpu \
  --profile balanced \
  --rule-pack generic-zh \
  --model-device CPU \
  --no-serve

claimledger audit \
  --report REPORT.docx \
  --sources EVIDENCE_DIR \
  --case-name intel-balanced-auto \
  --profile balanced \
  --rule-pack generic-zh \
  --model-device AUTO \
  --no-serve
```

CPU fallback 需在禁用或不可见 GPU 的环境重新执行 CPU 命令，不能只把 `AUTO` 的结果改名。

## 结果

| 场景 | 设备 | 首次加载 | 结论抽取 | Embedding | Reranker | 总耗时 | 峰值 RSS | 状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| CPU | | | | | | | | |
| GPU/AUTO | | | | | | | | |
| CPU fallback | | | | | | | | |

同时记录：

- `openvino_devices` 原始输出；
- 每个任务的 `artifact_manifest.json`；
- 模型 installation manifest 与规则包哈希；
- 是否发生超时、OOM、驱动回退或模型角色错误；
- 临时网关是否在审计后退出；
- 未检测到 GPU 时明确写“未验证”，不能写“兼容”。
