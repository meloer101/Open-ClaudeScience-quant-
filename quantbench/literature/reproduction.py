from __future__ import annotations

from typing import Any

from quantbench.literature.agent import FactorExtraction

# Maps the paper's reported-result keys to the metric keys our engines actually
# produce (quantbench/engine/*). "rank_ic" and "ic" are the same thing under
# different names in the two vocabularies.
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "sharpe": ("sharpe",),
    "annual_return": ("annual_return", "annualized_return", "cagr"),
    "rank_ic": ("ic", "rank_ic", "mean_ic"),
}

_LABELS = {
    "sharpe": "Sharpe",
    "annual_return": "Annual return",
    "rank_ic": "Rank IC",
}


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _reproduced_value(metrics: dict[str, Any], reported_key: str) -> float | None:
    for candidate in _METRIC_ALIASES.get(reported_key, (reported_key,)):
        if candidate in metrics:
            value = _as_float(metrics[candidate])
            if value is not None:
                return value
    return None


def build_reproduction_comparison(
    extraction: FactorExtraction,
    metrics: dict[str, Any],
    *,
    literature_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Side-by-side of what the paper CLAIMED vs. what we MEASURED. A large gap
    is itself a finding (GAP 4.3: 'reproduced results not matching the paper is
    valuable research output'), so this table is a first-class artifact rather
    than a pass/fail check."""
    reported = extraction.reported_results or {}
    rows: list[dict[str, Any]] = []
    for reported_key in ("sharpe", "annual_return", "rank_ic"):
        reported_value = _as_float(reported.get(reported_key))
        reproduced_value = _reproduced_value(metrics, reported_key)
        if reported_value is None and reproduced_value is None:
            continue
        delta = (
            reproduced_value - reported_value
            if reported_value is not None and reproduced_value is not None
            else None
        )
        rows.append(
            {
                "metric": reported_key,
                "label": _LABELS[reported_key],
                "reported": reported_value,
                "reproduced": reproduced_value,
                "delta": None if delta is None else round(delta, 4),
            }
        )
    return {
        "factor_name": extraction.factor_name,
        "literature_source": literature_source,
        "reported_sample_period": reported.get("sample_period"),
        "reported_universe": reported.get("universe"),
        "assumptions": extraction.assumptions,
        "known_caveats": extraction.known_caveats,
        "rows": rows,
        "note": (
            "Reported figures are the paper's own claims; reproduced figures are this run's "
            "measured metrics. Differences are expected and are themselves a research finding — "
            "implementation choices, sample/universe differences, and survivorship/PIT effects "
            "all move the numbers."
        ),
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = ["## 文献复现对比 (Reproduction vs. Reported)", ""]
    source = comparison.get("literature_source") or {}
    if source.get("citation"):
        lines.append(f"来源：{source['citation']}")
    anchors = source.get("page_anchors")
    if anchors:
        lines.append(f"引用页码：{', '.join(str(page) for page in anchors)}")
    if comparison.get("reported_sample_period"):
        lines.append(f"论文样本区间：{comparison['reported_sample_period']}")
    if comparison.get("reported_universe"):
        lines.append(f"论文 universe：{comparison['reported_universe']}")
    lines.append("")
    rows = comparison.get("rows") or []
    if rows:
        lines.append("| 指标 | 论文报告 | 本地复现 | 差异 |")
        lines.append("|---|---|---|---|")
        for row in rows:
            reported = "—" if row["reported"] is None else f"{row['reported']:.3f}"
            reproduced = "—" if row["reproduced"] is None else f"{row['reproduced']:.3f}"
            delta = "—" if row["delta"] is None else f"{row['delta']:+.3f}"
            lines.append(f"| {row['label']} | {reported} | {reproduced} | {delta} |")
    else:
        lines.append("_论文未报告可比对的量化指标（Sharpe / 年化收益 / Rank IC），无法生成对比表。_")
    lines.append("")
    if comparison.get("assumptions"):
        lines.append("**复现时的假设（论文未明确、由模型推断）：**")
        lines.extend(f"- {item}" for item in comparison["assumptions"])
        lines.append("")
    if comparison.get("known_caveats"):
        lines.append("**已知局限：**")
        lines.extend(f"- {item}" for item in comparison["known_caveats"])
        lines.append("")
    lines.append(f"> {comparison['note']}")
    return "\n".join(lines)
