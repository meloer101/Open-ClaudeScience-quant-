from datetime import datetime, timezone


def build_research_note(
    run_id: str,
    config: dict,
    metrics: dict[str, float],
    data_hash: str,
    warnings: list[str] | None = None,
    summary: str = "",
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
## Coordinator 总结
{summary or "(未生成总结)"}

## 局限性声明（Phase 0 尚未做完整审查）
以下问题尚未做自动检查（Phase 2 的 Reviewer Agent 会覆盖）：
- 样本外表现是否衰减
- 手续费敏感性
- 参数稳定性
- 是否依赖极端行情或少数交易

## 代码
完整可复现代码见 `signal.py`（若已生成）。
"""
