# ClaimLedger

> AI 写完以后，谁来证明它可以交付？

ClaimLedger 是一个开源的、本地优先的报告证据审计 Skill。它读取一份已经成稿的 DOCX 报告和用户提供的封闭证据包，把报告拆成可核查结论，定位原文证据，检查数字、日期、单位、实体和统计口径，并在人类确认后生成可追溯的交付包。

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](.qoder/skills/claimledger-audit/pyproject.toml)

当前开源版本：`v0.5.1`

## 为什么需要 ClaimLedger

普通审稿 Prompt 通常只能给出一段“可能有误”的建议，无法回答这些交付问题：

- 这条结论对应哪份原文件、哪一页、哪一段或哪个单元格？
- 报告中的数字、日期、主体和统计口径是否与证据一致？
- 多份证据互相冲突时，冲突是否被完整保留？
- 谁批准了修改、驳回或豁免，理由是什么？
- 最终交付物是否仍对应审计时的原始文件？

ClaimLedger 将流程固定为：

```text
待审报告 + 封闭证据包
        ↓
结论清单 → 原文证据 → 差异检查 → 人工决定 → 交付门禁
        ↓
批注 Word + Excel 台账 + 审计 JSON + 哈希清单 + 新版 Word
```

## 核心能力

- 解析 DOCX 报告，以及 PDF、DOCX、XLSX、PNG、JPG、TIFF 证据；
- 将报告拆为可独立核查的结论；
- 保存 PDF 页码与坐标、Word 段落或表格单元格、Excel 工作表与单元格、OCR 坐标；
- 核查数字、日期、单位数量级、主体、品类、地区、期间、分母、含税口径和时效性；
- 显示来源冲突、弱支持、过期证据和低置信度 OCR；
- 对原始文件和正式产物记录 SHA-256；
- 通过本机审阅页记录 `accept`、`reject`、`replace` 和 `waive` 决定；
- 只有在证据完整且高风险项被有效处理后，才允许生成最终 DOCX；
- 默认仅监听 `127.0.0.1`，不把报告和证据发送到云端。

## 适用范围

适合：

- 采购与供应商评估报告；
- 运营月报、KPI 和服务报告；
- 行业研究和咨询交付；
- 尽调备忘录、方案事实核证；
- AI 生成或人工起草报告的交付前复核。

不适合：

- 报告写作、改写或总结；
- 通用 OCR 或 RAG 问答；
- 联网事实核查；
- 隐私扫描；
- 招标要求与投标响应的逐条合规比对。

## 安装要求

- Python 3.11 或 3.12；
- macOS、Linux 或 Windows；
- 基础确定性流程不要求 GPU；
- OCR 与本地模型属于可选依赖，模型权重不包含在仓库中。

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/eason4kim-rocket/ClaimLedger.git
cd ClaimLedger/.qoder/skills/claimledger-audit
```

### 2. 创建隔离环境

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/claimledger.py doctor --json
```

Windows PowerShell 将 `.venv/bin/python` 替换为 `.venv\\Scripts\\python.exe`。

### 3. 生成合成演示案例

```bash
.venv/bin/python scripts/claimledger.py demo \
  --scenario operations \
  --output ../../../demos/operations-local \
  --json
```

### 4. 执行审计

```bash
.venv/bin/python scripts/claimledger.py audit \
  --report ../../../demos/operations-local/report.docx \
  --sources ../../../demos/operations-local/evidence \
  --case-name operations-local \
  --rule-pack operations-zh \
  --profile deterministic \
  --as-of-date 2026-08-05 \
  --open \
  --json
```

`deterministic` 适合首次运行和自动测试。日常本地审计建议使用 `lite`；扫描件需要先安装 OCR 依赖：

```bash
.venv/bin/python scripts/bootstrap.py --local-ai
.venv/bin/python scripts/claimledger.py models install --profile lite --execute --json
.venv/bin/python scripts/claimledger.py models verify --profile lite --device CPU --json
```

模型安装会下载第三方权重，执行前请检查磁盘空间和对应许可证。

## 在 Qoder 中使用

项目级 Skill 位于：

```text
.qoder/skills/claimledger-audit/
```

用 Qoder 打开仓库根目录后，新会话可以通过类似请求触发：

```text
请使用 ClaimLedger，以 Lite 模式根据 evidence 文件夹审计 report.docx。
先展示中文风险简报，不要替我自动批准、修改或豁免。
```

Skill 会在审计完成后展示“可信交付台”。卡片按钮只表达用户意图；高风险决定仍需复述并获得明确确认。

## 人工决定与交付门禁

```bash
.venv/bin/python scripts/claimledger.py status JOB_ID --json
.venv/bin/python scripts/claimledger.py brief JOB_ID --top 5 --json

.venv/bin/python scripts/claimledger.py decide JOB_ID FINDING_ID \
  --action replace \
  --replacement "经证据复核后的替换文本" \
  --actor reviewer \
  --json

.venv/bin/python scripts/claimledger.py export JOB_ID --annotated --ledger --json
.venv/bin/python scripts/claimledger.py export JOB_ID --final --json
```

`accept` 只表示确认风险发现，并不会自动解除高风险阻断。`replace` 必须重新核证；`reject` 和 `waive` 必须记录理由。原始报告不会被覆盖。

## 输出文件

每个审计任务使用独立目录：

- `annotated_report.docx`：带原生 Word 批注的待审报告；
- `claim_ledger.xlsx`：结论、检查项、候选证据、文件清单和决定日志；
- `audit.json`：机器可读的完整审计轨迹；
- `artifact_manifest.json`：输入、输出、规则、运行参数与 SHA-256；
- `delivery_report.docx`：人工门禁通过后生成的新版本。

## 运行模式

| 模式 | 用途 | 默认行为 |
|---|---|---|
| `deterministic` | 测试、首次运行、无 OCR 回退 | 不使用生成模型 |
| `lite` | 普通本地审计 | 必要时使用 PP-OCRv5 Mobile |
| `balanced` | 用户明确启用的复杂语义增强 | 使用本地 OpenVINO 生成、召回与重排模型 |

`balanced` 可能占用大量内存，不会因任务复杂而自动启用，也不存在云端降级路径。

## 合成黄金集与评测

`demos/golden-v2/` 包含采购、运营和咨询三个脱敏重构案例：100 条结论、49 条植入风险和 36 组证据。这些材料为合成演示数据，不是真实客户文件、客户背书或商用效果承诺。

当前仓库记录的 `lite` 结果为：

- 三行业风险识别 Precision：100%；
- 三行业风险识别 Recall：97.96%；
- 跨行业“文件 + 精确原文 + 精确定位”Top-5 召回率：91%。

结果、环境和限制见 [benchmark-report.md](docs/benchmark-report.md)。请勿将特定合成数据集成绩外推为生产环境准确率。

运行基准：

```bash
CLAIMLEDGER_DATA_DIR=/tmp/claimledger-benchmark \
  .venv/bin/python scripts/claimledger.py benchmark \
  --dataset ../../../demos/golden-v2/labels.json \
  --json
```

## 测试

```bash
cd .qoder/skills/claimledger-audit
CLAIMLEDGER_DATA_DIR=/tmp/claimledger-tests \
  .venv/bin/python -m pytest -p no:cacheprovider tests
```

测试覆盖解析、审计引擎、服务鉴权、模型网关、审阅记忆、导出安全、离线行为、打包和黄金集回归。

## 构建 Skill 发行包

在仓库根目录执行：

```bash
python3 tools/build-skill-package.py
```

构建脚本使用白名单打包，并检查 ZIP 中是否出现模型、虚拟环境、缓存、任务数据、数据库、日志、绝对路径或常见密钥格式。

## 仓库结构

```text
ClaimLedger/
├── .qoder/skills/claimledger-audit/
│   ├── SKILL.md
│   ├── agents/
│   ├── assets/
│   ├── references/
│   ├── scripts/
│   ├── src/claimledger/
│   └── tests/
├── demos/                         # 合成案例与黄金集
├── docs/                          # 架构、评测和已验证能力
├── tools/                         # 可复现构建工具
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

## 设计与验证文档

- [架构说明](docs/architecture.md)
- [基准测试报告](docs/benchmark-report.md)
- [v0.5.0 已验证能力](docs/verified-capabilities-v0.5.0.md)
- [v0.5.0 发布验证](docs/release-validation-v0.5.0.md)
- [一次请求完整流程](docs/one-request-flow-v0.4.1.md)

## 隐私与安全

- 默认仅处理用户明确提供的本地文件；
- 本地服务只监听 `127.0.0.1` 或 `localhost`；
- 不要把真实报告、证据、任务目录、数据库、模型或访问令牌提交到 Git；
- 对加密、损坏、超大、不支持或哈希变化的来源应停止或隔离处理；
- 自动审计不等于法律、财务、采购或专业批准；
- 发现漏洞时请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中附带敏感样本。

## 参与贡献

欢迎提交规则包、解析器、测试、合成案例和文档改进。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。涉及审计语义或交付门禁的改动必须同时提供正向、负向和回归测试。

## 许可证

代码和仓库内明确标注的合成材料使用 [Apache License 2.0](LICENSE)。第三方依赖和可选模型权重遵循各自许可证，且不包含在本仓库中。
