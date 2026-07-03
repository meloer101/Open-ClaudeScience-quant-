from datetime import datetime, timezone
from typing import Any


def build_research_note(
    run_id: str,
    config: dict,
    metrics: dict[str, float],
    data_hash: str,
    warnings: list[str] | None = None,
    summary: str = "",
    review_markdown: str = "",
    critic_markdown: str = "",
    lineage_markdown: str = "",
    metrics_ci: dict[str, dict[str, float]] | None = None,
) -> str:
    warnings = warnings or []
    warning_block = ""
    if warnings:
        bullet_list = "\n".join(f"- {w}" for w in warnings)
        warning_block = f"""
## ⚠️⚠️⚠️ DO NOT TRUST THIS RESULT ⚠️⚠️⚠️
{bullet_list}

---
"""

    if metrics:
        metrics_rows = _metrics_rows(metrics, metrics_ci)
        chart_block = "## 图表\n![equity curve](equity_curve.png)\n![drawdown](drawdown.png)\n"
    else:
        metrics_rows = "| (no backtest was run) | - |"
        chart_block = ""

    cache = config.get("cache") or {}
    data_slices = config.get("data_slices") or []

    return f"""# Research Note
{warning_block}
**Run ID:** {run_id}
**Date:** {datetime.now(timezone.utc).date().isoformat()}
**Model:** {config.get("model", "unknown")}
**Hypothesis:** {config.get("hypothesis", "")}

## 数据
- 数据来源: {cache.get("source", "unknown")}
- 数据分片: {_data_slice_summary(data_slices)}
- 复权/调整: {_adjustment_summary(data_slices, cache)}
- 数据版本 hash: `{data_hash}`

## 结果
| 指标 | 数值 |
|---|---:|
{metrics_rows}

{chart_block}
## Reviewer 审查报告
{review_markdown or "(未运行 Reviewer 审查)"}

## Critic Agent 独立复核
{critic_markdown or "(未运行 Critic Agent 独立复核)"}

{lineage_markdown}

## Coordinator 总结
{summary or "(未生成总结)"}

## 局限性声明
- Reviewer 是确定性启发式检查，不是形式化证明；未被标记不代表没有过拟合或未来函数。
- 基础数据来自免费源，数据缺口、复权、退市与 survivorship bias 仍需人工结合上下文判断。

## 代码
完整可复现代码见 `signal.py`（若已生成）。
"""


def build_cross_sectional_research_note(
    run_id: str,
    config: dict,
    metrics: dict[str, float],
    data_hash: str,
    warnings: list[str] | None = None,
    summary: str = "",
    data_quality: dict | None = None,
    review_markdown: str = "",
    critic_markdown: str = "",
    lineage_markdown: str = "",
    metrics_ci: dict[str, dict[str, float]] | None = None,
) -> str:
    warnings = warnings or []
    data_quality = data_quality or {}
    warning_block = ""
    if warnings:
        bullet_list = "\n".join(f"- {w}" for w in warnings)
        warning_block = f"""
## ⚠️ 数据与方法警告
{bullet_list}

---
"""

    metrics_rows = _metrics_rows(metrics, metrics_ci)
    cache = config.get("cache") or {}
    data_slices = config.get("data_slices") or []
    funding = config.get("funding") or {}
    universe = config.get("universe") or {}
    quality_rows = "\n".join(
        f"| {key} | {value if not isinstance(value, (list, dict)) else len(value)} |"
        for key, value in data_quality.items()
    )

    return f"""# Cross-Sectional Research Note
{warning_block}
**Run ID:** {run_id}
**Date:** {datetime.now(timezone.utc).date().isoformat()}
**Model:** {config.get("model", "unknown")}
**Hypothesis:** {config.get("hypothesis", "")}

## Universe
- 名称: {universe.get("name", "unknown")}{" (LIMITED SAMPLE, size=" + str(universe.get("sample_limit")) + ")" if universe.get("sample_limit") else ""}
- as_of_date: {universe.get("as_of_date", "unknown")}
- asset_class: {universe.get("asset_class", "unknown")}
- point_in_time: {universe.get("point_in_time", "unknown")}
- 标的数量: {len(universe.get("symbols", []))}
- 来源: {universe.get("source", "unknown")}
- 生存者偏差说明: {universe.get("survivorship_bias_note", "")}

## 数据
- 数据来源统计: {cache.get("sources", {})}
- 数据分片: {_data_slice_summary(data_slices)}
- 复权/调整: {_adjustment_summary(data_slices, cache)}
- Funding 数据来源统计: {funding.get("sources", {})}
- 数据版本 hash: `{data_hash}`

## 数据质量
| 项 | 数值 |
|---|---:|
{quality_rows or "| (no data quality report) | - |"}

## 结果
| 指标 | 数值 |
|---|---:|
{metrics_rows or "| (no backtest was run) | - |"}

## 图表
![equity curve](equity_curve.png)
![drawdown](drawdown.png)
![group returns](group_returns.png)
![rank ic](rank_ic.png)

## Reviewer 审查报告
{review_markdown or "(未运行 Reviewer 审查)"}

## Critic Agent 独立复核
{critic_markdown or "(未运行 Critic Agent 独立复核)"}

{lineage_markdown}

## Coordinator 总结
{summary or "(未生成总结)"}

## 局限性声明
- Universe 可能不是 point-in-time；具体偏差以本报告 Universe 区块和警告区块为准。
- Reviewer 是确定性启发式检查，不是形式化证明；未被标记不代表没有过拟合或未来函数。
- 基础数据来自免费源，退市、收购、拆股和缺口需要结合数据质量报告判断。

## 代码
完整可复现因子代码见 `signal.py`；universe 定义见 `universe.yaml`。
"""


def build_portfolio_research_note(
    run_id: str,
    config: dict,
    outcome: Any,
    warnings: list[str] | None = None,
    summary: str = "",
    review_markdown: str = "",
    critic_markdown: str = "",
    metrics_ci: dict[str, dict[str, float]] | None = None,
) -> str:
    """`outcome` is a quantbench.portfolio.pipeline.PortfolioOptimizationOutcome.
    Typed as Any here (rather than importing the dataclass) to avoid
    quantbench.skills depending on quantbench.portfolio - report-building stays
    a leaf module, matching how build_research_note/build_cross_sectional_research_note
    only take plain dicts/strings, never engine result objects."""
    warnings = warnings or []
    warning_block = ""
    if warnings:
        bullet_list = "\n".join(f"- {w}" for w in warnings)
        warning_block = f"""
## ⚠️ 组合优化警告
{bullet_list}

---
"""

    metrics = outcome.combined.metrics
    metrics_rows = _metrics_rows(metrics, metrics_ci)
    weight_rows = "\n".join(f"| {run_id_} | {weight:.4f} |" for run_id_, weight in outcome.weights.items())

    comparison_rows = "\n".join(
        f"| {method} | {row['train_sharpe']} | {row['test_sharpe'] if row['test_sharpe'] is not None else '-'} | "
        f"{'✓ 已选中' if method == outcome.selected_method else ''} |"
        for method, row in outcome.comparison_table.items()
    )

    correlation_rows = "\n".join(
        f"| {run_a} | " + " | ".join(f"{outcome.correlation.get(run_a, {}).get(run_b, '')}" for run_b in outcome.correlation)
        for run_a in outcome.correlation
    )
    correlation_header = "| | " + " | ".join(outcome.correlation.keys()) + " |"

    return f"""# Portfolio Optimization Research Note
{warning_block}
**Run ID:** {run_id}
**Date:** {datetime.now(timezone.utc).date().isoformat()}
**Model:** {config.get("model", "unknown")}
**Hypothesis:** {config.get("hypothesis", "")}
**成分 run_id:** {", ".join(config.get("constituent_run_ids", []))}

## 组合优化
- 选中方法: **{outcome.selected_method}**（默认稳健法；max_sharpe 无论是否被选中，都只作为对照，不是推荐）
- 训练/测试切分点: {outcome.train_test_split_index}
- 重叠观测数: {outcome.overlap_observations}
- 多样化比率（加权平均波动 / 组合波动，越大于 1 说明组合分散效果越好）: {metrics.get("diversification_ratio")}

### 权重（在训练集上拟合，样本外表现见下方对照表）
| run_id | 权重 |
|---|---:|
{weight_rows}

### 方法对照表（诚实机器：max_sharpe 样本内通常最好看，样本外常常反而更差）
| 方法 | 样本内夏普 | 样本外夏普 | |
|---|---:|---:|---|
{comparison_rows}

### 成分因子相关性矩阵
{correlation_header}
|{"---|" * (len(outcome.correlation) + 1)}
{correlation_rows}

## 组合结果（全样本，使用训练集拟合的固定权重）
| 指标 | 数值 |
|---|---:|
{metrics_rows}

## 图表
![equity curve](equity_curve.png)
![drawdown](drawdown.png)

## Reviewer 审查报告
{review_markdown or "(未运行 Reviewer 审查)"}

## Critic Agent 独立复核
{critic_markdown or "(未运行 Critic Agent 独立复核)"}

## Coordinator 总结
{summary or "(未生成总结)"}

## 局限性声明
- 组合优化不做杠杆/做空，权重恒定在 [0, max_weight] 且和为 1；不做滚动再配权（一次 train 拟合，test 上固定权重）。
- 换手率/成本只按权重再平衡漂移估算，不建模各成分因子底层持仓的交易成本。
- 被选中方法的样本内夏普存在选择偏差（从多个方法/候选中挑出来的），不代表统计显著；对照表和样本外表现是判断是否过拟合的主要依据，不是样本内数字本身。
- Reviewer 是确定性启发式检查，不是形式化证明；未被标记不代表没有过拟合。

## 代码
组合权重见 `portfolio_weights.json`；完整方法对照与诊断见 `portfolio_summary.json`；组合收益序列见 `backtest_result.json`。
"""


def _metrics_rows(metrics: dict[str, float], metrics_ci: dict[str, dict[str, float]] | None = None) -> str:
    rows = []
    intervals = metrics_ci or {}
    for key, value in metrics.items():
        interval = intervals.get(key)
        if key in {"sharpe", "annual_return"} and interval:
            rows.append(f"| {key} | {value} [95% CI: {interval['lower']}, {interval['upper']}] |")
        else:
            rows.append(f"| {key} | {value} |")
    return "\n".join(rows)


def _data_slice_summary(data_slices: list[dict]) -> str:
    if not data_slices:
        return "未记录分片"
    total_rows = sum(int(item.get("rows") or 0) for item in data_slices)
    return f"{len(data_slices)} slices / {total_rows} rows"


def _adjustment_summary(data_slices: list[dict], cache: dict) -> str:
    adjustments = []
    for item in data_slices:
        adjustment = item.get("adjustment")
        if isinstance(adjustment, dict):
            adjustments.append(
                f"{adjustment.get('method', 'unknown')}, dividend_reinvested={adjustment.get('dividend_reinvested')}"
            )
    if not adjustments and isinstance(cache.get("adjustment"), dict):
        adjustment = cache["adjustment"]
        adjustments.append(
            f"{adjustment.get('method', 'unknown')}, dividend_reinvested={adjustment.get('dividend_reinvested')}"
        )
    if not adjustments:
        return "unknown"
    unique = sorted(set(adjustments))
    return "; ".join(unique[:3])
