# llm-json-contract-miner

llm-json-contract-miner 是一个离线 LLM JSON 输出契约挖掘工具。它读取多次模型结构化输出的 JSON/JSONL 文件，统计实际字段路径、类型分布、缺失率、null 比例、枚举候选、异常样本，并与期望 contract / JSON Schema 做 drift 对比，输出 JSON Schema 草案、Markdown、JSON、CSV、JUnit、修复计划报告和 CI gate 退出码。

它适合依赖 LLM JSON 输出的应用团队、eval 维护者、agent 工程团队和 CI 流水线，用来回答：

- 模型实际输出的字段是否稳定。
- 哪些字段应当 required，哪些只是 optional。
- 枚举值是否出现未登记扩展。
- 与当前 contract 相比有哪些类型漂移、缺字段、新字段。
- 是否可以安全更新 schema 或放行 PR。

项目只使用 Python 标准库，兼容 Python 3.9+，没有外部运行时依赖。

## 适用场景

- **结构化输出验收**：上线前用真实模型样本挖掘字段、类型和 required/optional。
- **eval 回归分析**：比较新 prompt、新模型、新工具调用链的 JSON 输出是否漂移。
- **CI gate**：当缺少 expected 字段、类型不匹配或风险分数过高时阻断 PR。
- **agent 开发**：让 Codex、Claude Code、Cursor 等 agent 在改 JSON contract 前先生成 evidence report。
- **schema 更新**：把观察到的输出生成 JSON Schema 草案，供人工 review 后纳入仓库。

## 安装

开发安装：

```bash
python -m pip install -e .
```

不安装也可以通过 `PYTHONPATH=src` 直接运行：

```bash
PYTHONPATH=src python -m llm_json_contract_miner examples/outputs.jsonl --no-fail
```

## 快速开始

```bash
llm-json-contract-miner examples/outputs.jsonl \
  --expected examples/expected.schema.json \
  --out reports \
  --formats markdown,json,junit,schema,csv,fix-plan
```

生成文件：

- `reports/contract-report.md`：给 reviewer 看的字段和 drift 摘要。
- `reports/contract-report.json`：给 agent、脚本或 dashboard 使用的结构化报告。
- `reports/schema.draft.json`：从实际样本推断的 JSON Schema 草案。
- `reports/junit.xml`：CI 可消费的失败项。
- `reports/fields.csv`：字段路径表，适合表格审阅。
- `reports/contract-fix-plan.md`：面向 maintainer / coding agent 的修复计划。

## CLI

```bash
llm-json-contract-miner INPUT.jsonl [more.json more.jsonl] [options]
```

常用参数：

- `--expected path`：期望 contract / JSON Schema 文件。
- `--out reports`：报告输出目录。
- `--formats markdown,json,junit,schema,csv,fix-plan`：输出格式。
- `--enum-limit 20`：字段枚举候选的最大不同值数量。
- `--required-ratio 1.0`：判断 required 的样本出现比例。
- `--fail-score 70`：风险分数达到阈值时返回退出码 1。
- `--no-fail`：报告照常生成，但总是退出 0，适合探索模式。
- `--summary`：把 Markdown 摘要打印到 stdout。

## API

```python
from llm_json_contract_miner import analyze_samples

samples = [
    {"id": "a", "status": "ok", "score": 0.9},
    {"id": "b", "status": "needs_review", "score": 0.5},
]

report = analyze_samples(samples)
print(report.schema)
print(report.risk_score)
```

## 输入格式

支持：

- `.json`：单个 JSON object，或 object 数组。
- `.jsonl`：每行一个 JSON object；空行和 `#` 开头注释会跳过。

样本可以是任意 JSON 值，但实际 LLM structured output 通常是 object。数组内部字段会用 `[]` 路径表示，例如：

- `$.answer.citations[]`
- `$.tool_calls[].name`
- `$.tool_calls[].success`

## Contract 推断模型

挖掘流程：

1. 遍历每个样本的嵌套对象、数组和标量。
2. 为每个路径统计出现次数、缺失次数、null 次数、类型分布、枚举候选和样本索引。
3. 根据 `required_ratio` 判断 required 字段。
4. 根据 dominant type 构造 JSON Schema 草案。
5. 与 `--expected` contract 对比，生成 drift findings。
6. 将异常和 drift 映射为风险分数与 CI 退出码。

## Drift 类型

- `missing_expected_field`：期望 contract 声明字段，但样本没有观察到。
- `type_mismatch`：观察到的类型与期望类型无交集。
- `enum_drift`：观察值超出期望枚举。
- `new_observed_field`：样本出现了 contract 未声明字段。
- `mixed_types`：同一路径出现多个 JSON 类型。
- `required_with_nulls`：字段几乎 required，但出现 null。
- `near_required_missing`：字段在大多数样本出现，但仍有缺失。

## CI 集成

GitHub Actions 示例：

```yaml
- name: Mine LLM JSON contract
  run: |
    python -m pip install -e .
    llm-json-contract-miner eval-output/*.jsonl \
      --expected contracts/answer.schema.json \
      --out reports/contract \
      --formats markdown,json,junit,schema,csv
```

如果风险分数达到 `--fail-score`，或存在 error 级 drift，命令会返回非 0。探索阶段可以加 `--no-fail`。

## Agent 集成建议

- 让 coding agent 在修改 structured output prompt 后运行本工具。
- 把 `contract-report.md` 粘到 PR 描述，方便 reviewer 快速看 drift。
- 把 `contract-report.json` 作为后续 agent 修复任务输入。
- 把 `contract-fix-plan.md` 作为修复工单：它会把问题分成 schema 更新、prompt/decoder 修复、样本清洗和人工 review，并附可复制的 agent repair prompt。
- 只把 `schema.draft.json` 当作草案，不要绕过人工 review 自动覆盖正式 contract。

## 限制

- 本工具不调用模型，不判断自然语言答案质量。
- JSON Schema 生成是保守草案，不替代产品 contract 设计。
- 枚举候选基于已观察样本，样本少时容易过拟合。
- `required_ratio` 默认 1.0，样本质量差时可以调低，但需要人工确认。

## 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m llm_json_contract_miner examples/outputs.jsonl --expected examples/expected.schema.json --no-fail
```

发布前检查：

- README 中英双语。
- `python -m unittest discover -s tests` 通过。
- GitHub Actions 通过 Python 3.9 和 3.12。
- 不提交真实样本中的个人信息、密钥或客户数据。

## English

llm-json-contract-miner is an offline contract mining tool for LLM JSON outputs. It reads repeated model outputs from JSON or JSONL files, discovers actual field paths, type distributions, required and optional fields, null and missing rates, enum candidates, anomalous samples, and drift against an expected contract or JSON Schema.

It produces:

- A draft JSON Schema inferred from observed samples.
- Markdown reports for reviewers.
- JSON reports for agents and automation.
- CSV field inventories.
- JUnit XML for CI gates.
- A contract fix plan for maintainers and coding agents.

The project uses only the Python standard library and supports Python 3.9+.

### Use Cases

- Validate structured LLM outputs before a release.
- Detect schema drift after prompt, model, retrieval, or tool changes.
- Generate reviewable evidence for pull requests.
- Help coding agents decide whether a contract update is safe.
- Maintain eval fixtures for JSON-producing LLM applications.

### Install

```bash
python -m pip install -e .
```

Or run without installation:

```bash
PYTHONPATH=src python -m llm_json_contract_miner examples/outputs.jsonl --no-fail
```

### CLI

```bash
llm-json-contract-miner examples/outputs.jsonl \
  --expected examples/expected.schema.json \
  --out reports \
  --formats markdown,json,junit,schema,csv,fix-plan
```

Options:

- `--expected`: expected contract / JSON Schema file.
- `--out`: report directory.
- `--formats`: comma-separated report formats.
- `--enum-limit`: maximum distinct scalar values to keep as enum candidates.
- `--required-ratio`: observed ratio used to infer required fields.
- `--fail-score`: risk threshold for CI failure.
- `--no-fail`: always exit 0 after writing reports.
- `--summary`: print Markdown to stdout.

### API

```python
from llm_json_contract_miner import analyze_samples

report = analyze_samples([
    {"id": "a", "status": "ok"},
    {"id": "b", "status": "needs_review"},
])
print(report.schema)
```

### Input Format

- `.json`: one object or a list of objects.
- `.jsonl`: one JSON value per line; blank lines and comment lines are ignored.

Nested arrays are represented with `[]` in paths, such as `$.tool_calls[].name`.

### CI Gate

The command exits with status 1 when the risk score reaches `--fail-score` or an error-level drift finding is present. Use `--no-fail` for exploration or report-only pipelines.

### Fix Plan

`contract-fix-plan.md` turns drift evidence into a reviewable work order. It groups findings into schema updates, prompt/decoder repairs, sample hygiene, and human review, then includes a copyable agent repair prompt. Use it as the handoff artifact after prompt, model, parser, or tool-output changes.

### Limitations

This tool does not call an LLM, judge semantic answer quality, or guarantee that the inferred schema is product-ready. Treat generated schemas as review drafts.
