from datetime import datetime, timezone


def build_research_note(
    run_id: str,
    config: dict,
    metrics: dict[str, float],
    data_hash: str,
    warnings: list[str] | None = None,
    summary: str = "",
    review_markdown: str = "",
    lineage_markdown: str = "",
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
        metrics_rows = "\n".join(f"| {key} | {value} |" for key, value in metrics.items())
        chart_block = "## 图表\n![equity curve](equity_curve.png)\n![drawdown](drawdown.png)\n"
    else:
        metrics_rows = "| (no backtest was run) | - |"
        chart_block = ""

    cache = config.get("cache") or {}

    return f"""# Research Note
{warning_block}
**Run ID:** {run_id}
**Date:** {datetime.now(timezone.utc).date().isoformat()}
**Model:** {config.get("model", "unknown")}
**Hypothesis:** {config.get("hypothesis", "")}

## 数据
- 数据来源: {cache.get("source", "unknown")}
- 数据版本 hash: `{data_hash}`

## 结果
| 指标 | 数值 |
|---|---:|
{metrics_rows}

{chart_block}
## Reviewer 审查报告
{review_markdown or "(未运行 Reviewer 审查)"}

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
    lineage_markdown: str = "",
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

    metrics_rows = "\n".join(f"| {key} | {value} |" for key, value in metrics.items())
    cache = config.get("cache") or {}
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
