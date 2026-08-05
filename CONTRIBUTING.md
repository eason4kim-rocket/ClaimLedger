# Contributing to ClaimLedger

感谢你改进 ClaimLedger。这个项目处理交付前证据审计，因此可追溯性、隐私和失败时的安全行为优先于功能数量。

## 开始开发

```bash
git clone https://github.com/eason4kim-rocket/ClaimLedger.git
cd ClaimLedger/.qoder/skills/claimledger-audit
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

建议从 `main` 创建短生命周期分支：

```bash
git switch -c feat/short-description
```

## 提交前检查

```bash
cd .qoder/skills/claimledger-audit
CLAIMLEDGER_DATA_DIR=/tmp/claimledger-tests \
  .venv/bin/python -m pytest -p no:cacheprovider tests

cd ../../..
python3 tools/build-skill-package.py
```

Pull Request 应说明：

- 解决的问题和行为变化；
- 新增或修改的稳定接口；
- 已运行的测试；
- 失败案例和兼容性影响；
- 是否涉及证据、个人数据、模型权重或第三方许可。

## 审计规则和交付门禁

- 新增问题代码或风险等级时，同时更新规则说明和回归测试；
- 不得让模型生成不存在的文件名、页码、坐标或引文；
- 不得把低置信度 OCR 结果当作已确认事实；
- 不得绕过人工决定直接导出高风险最终稿；
- 修改哈希、决定日志或导出逻辑时，必须增加篡改和失败测试；
- 解析失败应返回明确状态，不得静默丢弃证据。

## 测试数据与隐私

只提交以下材料：

- 自行生成的合成案例；
- 明确允许再分发的公开材料；
- 不含真实个人、客户、供应商、账号、密钥和内部路径的最小复现。

不要提交真实报告、证据包、运行数据库、任务产物、模型权重或日志。若问题只能用敏感材料复现，请先按 [SECURITY.md](SECURITY.md) 私下联系维护者。

## 代码风格

- 保持 Python 3.11 兼容；
- 稳定 CLI、JSON 字段和状态枚举尽量向后兼容；
- 新功能应包含正向、负向和回归测试；
- 注释解释非显然的安全约束，不重复代码本身；
- 文档中的效果数字必须链接到可复现实验或明确标注限制。

提交贡献即表示你有权提供相关代码和材料，并同意按 Apache License 2.0 发布。

