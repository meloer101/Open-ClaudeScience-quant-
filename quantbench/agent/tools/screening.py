import json
import math
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from quantbench.agent.constants import SIGNAL_FILE_HARNESS, SIGNAL_FILE_HEADER
from quantbench.agent.helpers.benchmarks import _benchmark_symbol_for_asset
from quantbench.agent.helpers.critic_support import _run_critic_for_context
from quantbench.agent.helpers.research_notes_support import (
    _backtest_payload_with_factor_metadata,
    _data_slices_from_cache,
    _factor_metadata,
    _metrics_ci_for_run,
    _rerun_cross_with_code,
    _review_warning_messages,
)
from quantbench.agent.helpers.sensitivity import (
    _cross_execution_sensitivity,
    _metrics_without_borrow,
    _neutralization_comparison,
)
from quantbench.agent.run_context import _RunContext
from quantbench.artifact.store import ArtifactStore
from quantbench.config import CRITIC_MODEL
from quantbench.data.cache import file_sha256
from quantbench.data.universe import UniverseDefinition
from quantbench.engine.costs import BorrowCostConfig, LiquidityCostConfig
from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest
from quantbench.engine.execution import ExecutionConfig
from quantbench.review import CriticReport, ReviewFinding, ReviewReport, determine_verdict, run_review
from quantbench.review.pbo import PBOResult, probability_of_backtest_overfitting
from quantbench.review.report import _dsr_finding, _pbo_finding
from quantbench.skills.codeexec import run_signal_code_panel
from quantbench.skills.data_quality import validate_universe_data
from quantbench.skills.plot import (
    save_drawdown_plot,
    save_equity_curve_plot,
    save_group_returns_plot,
    save_ic_plot,
    save_risk_attribution_plot,
)
from quantbench.skills.report import build_cross_sectional_research_note


def _run_screen_candidate(
    run_store: ArtifactStore,
    critic_llm,
    model: str,
    parent_run_id: str,
    universe: UniverseDefinition,
    panel: pd.DataFrame,
    cache_meta: dict[str, Any],
    funding_rates: pd.DataFrame | None,
    funding_meta: dict[str, Any] | None,
    candidate: dict[str, str],
    start: str,
    end: str,
    timeframe: str,
    n_groups: int,
    cost_bps: float,
    execution: ExecutionConfig,
    liquidity_config: LiquidityCostConfig | None,
    borrow_config: BorrowCostConfig,
    borrow_rates: pd.DataFrame | None,
    neutralize_dims: list[str],
    sector: pd.Series | None,
    benchmark_returns: Any,
    effective_trials: int,
) -> dict[str, Any]:
    child = run_store.create_run(f"Screen factor {candidate['name']} from {parent_run_id}")
    critic_model = str(getattr(critic_llm, "model", CRITIC_MODEL))
    ctx = _RunContext()
    ctx.universe = universe
    ctx.panel_df = panel
    ctx.cache_meta = cache_meta
    ctx.cross_sectional = True
    ctx.signal_code = candidate["code"]
    ctx.cost_bps = cost_bps
    # Written before the risky calls below so a candidate that fails mid-backtest
    # still leaves its code and parent linkage on disk - screen_factors expects
    # per-candidate failures, and library/lineage only read parent_run_id from
    # config.yaml/manifest.json, never from error.json.
    child.save_code("signal.py", SIGNAL_FILE_HEADER + candidate["code"] + SIGNAL_FILE_HARNESS)
    child.save_config(
        {
            "hypothesis": f"Screen factor {candidate['name']}",
            "model": model,
            "critic_model": critic_model,
            "universe": universe.to_dict(),
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "execution": execution.to_dict(),
            "cost_model": "liquidity_aware" if liquidity_config is not None else "fixed_bps",
            "borrow_model": "tiered_adv_assumption" if borrow_config.enabled else "not_applied",
            "neutralize": neutralize_dims,
            "parent_run_id": parent_run_id,
            "screen_candidate": candidate["name"],
            "factor_metadata": _factor_metadata(candidate["code"], len(panel)),
        }
    )
    try:
        ctx.data_quality = validate_universe_data(panel, universe, end=end)
        factor_values = run_signal_code_panel(candidate["code"], panel, usage_sink=ctx.sandbox_usage)
        backtest = run_cross_sectional_backtest(
            panel,
            None,
            n_groups=n_groups,
            cost_bps=cost_bps,
            membership_intervals=universe.membership_intervals,
            funding_rates=funding_rates,
            execution=execution,
            liquidity_cost_config=liquidity_config,
            borrow_rates=borrow_rates,
            neutralize=neutralize_dims,
            sector=sector,
            factor_values=factor_values,
        )
        funding_sensitivity = None
        if funding_rates is not None and not funding_rates.empty:
            no_funding_metrics = run_cross_sectional_backtest(
                panel,
                None,
                n_groups=n_groups,
                cost_bps=cost_bps,
                membership_intervals=universe.membership_intervals,
                execution=execution,
                liquidity_cost_config=liquidity_config,
                borrow_rates=borrow_rates,
                neutralize=neutralize_dims,
                sector=sector,
                factor_values=factor_values,
            ).metrics
            funding_sensitivity = {
                "sharpe_before_funding": no_funding_metrics.get("sharpe"),
                "sharpe_after_funding": backtest.metrics.get("sharpe"),
                "funding_rows": len(funding_rates),
                "funding_sources": (funding_meta or {}).get("sources", {}),
            }
        if funding_meta is not None:
            funding_meta = {**funding_meta, "alignment": backtest.funding_coverage}
        ctx.last_metrics = backtest.metrics

        panel_path = child.run_dir / "panel.parquet"
        panel.to_parquet(panel_path, index=False)
        child.save_json("backtest_result.json", _backtest_payload_with_factor_metadata(backtest, candidate["code"], len(panel)))
        child.save_json("data_quality_report.json", ctx.data_quality.to_dict())
        save_equity_curve_plot(backtest.equity_curve, child.run_dir / "equity_curve.png")
        save_drawdown_plot(backtest.drawdown, child.run_dir / "drawdown.png")
        save_group_returns_plot(backtest.group_returns, child.run_dir / "group_returns.png")
        save_ic_plot(backtest.ic_series, child.run_dir / "rank_ic.png")

        benchmark_symbol = _benchmark_symbol_for_asset(universe.asset_class)
        review_report = run_review(
            code=candidate["code"],
            returns=backtest.returns,
            cost_bps=cost_bps,
            rerun_at_cost=lambda bps: run_cross_sectional_backtest(
                panel,
                None,
                n_groups=n_groups,
                cost_bps=bps,
                membership_intervals=universe.membership_intervals,
                funding_rates=funding_rates,
                execution=execution,
                liquidity_cost_config=liquidity_config,
                borrow_rates=borrow_rates,
                neutralize=neutralize_dims,
                sector=sector,
                factor_values=factor_values,
            ).metrics,
            rerun_with_code=lambda code: _rerun_cross_with_code(
                code, panel, n_groups, cost_bps, universe.membership_intervals
            ),
            out_of_sample_data=panel,
            run_on_data=lambda data: _rerun_cross_with_code(
                candidate["code"], data, n_groups, cost_bps, universe.membership_intervals
            ) or {},
            benchmark_returns=benchmark_returns,
            benchmark_symbol=benchmark_symbol,
            factor_panel=backtest.factor_panel,
            n_groups=n_groups,
            turnover_annual=backtest.metrics.get("turnover_annual"),
            n_trials=effective_trials,
            universe_coverage=(cache_meta.get("coverage_report") if isinstance(cache_meta, dict) else None),
            funding_cost_sensitivity=funding_sensitivity,
            execution_sensitivity=_cross_execution_sensitivity(
                panel,
                factor_values,
                n_groups,
                cost_bps,
                universe.membership_intervals,
                funding_rates,
                liquidity_config,
                borrow_rates,
                neutralize_dims,
                sector,
            ),
            capacity_curve=backtest.capacity_curve,
            long_short_contribution=backtest.long_short_contribution,
            borrow_cost_sensitivity={
                "sharpe_before_borrow": _metrics_without_borrow(
                    panel,
                    factor_values,
                    n_groups,
                    cost_bps,
                    universe.membership_intervals,
                    funding_rates,
                    execution,
                    liquidity_config,
                    neutralize_dims,
                    sector,
                ).get("sharpe"),
                "sharpe_after_borrow": backtest.metrics.get("sharpe"),
            }
            if borrow_config.enabled
            else None,
            ic_series=backtest.ic_series,
            ic_significance=backtest.ic_significance,
            mcp_calls=ctx.mcp_calls,
            execution=execution.to_dict(),
            universe=universe.to_dict(),
        )
        ctx.review_report = review_report
        child.save_json("review_report.json", review_report.to_dict())
        ctx.warnings.extend(_review_warning_messages(review_report))
        neutralization_comparison = _neutralization_comparison(
            panel,
            factor_values,
            n_groups,
            cost_bps,
            universe.membership_intervals,
            funding_rates,
            execution,
            liquidity_config,
            borrow_rates,
            neutralize_dims,
            sector,
        )
        if neutralization_comparison:
            save_risk_attribution_plot(neutralization_comparison, child.run_dir / "risk_attribution.png")

        summary = (
            f"Screened factor {candidate['name']}: deterministic verdict {review_report.verdict}, "
            f"Sharpe {backtest.metrics.get('sharpe')}."
        )
        _run_critic_for_context(
            ctx,
            child,
            critic_llm,
            summary,
            {
                "asset_class": universe.asset_class,
                "universe": universe.name,
                "symbols": len(universe.symbols),
                "cost_bps": cost_bps,
                "start": start,
                "end": end,
                "timeframe": timeframe,
                "execution": execution.to_dict(),
                "cost_model": "liquidity_aware" if liquidity_config is not None else "fixed_bps",
                "borrow_model": "tiered_adv_assumption" if borrow_config.enabled else "not_applied",
                "neutralize": neutralize_dims,
            },
        )
        data_hash = f"sha256:{file_sha256(panel_path)}"
        code_path = child.run_dir / "signal.py"
        code_hash = f"sha256:{file_sha256(code_path)}"
        config = {
            "hypothesis": f"Screen factor {candidate['name']}",
            "model": model,
            "critic_model": critic_model,
            "data_path": str(panel_path),
            "cache": cache_meta,
            "data_slices": _data_slices_from_cache(cache_meta),
            "funding": funding_meta,
            "universe": universe.to_dict(),
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "execution": execution.to_dict(),
            "cost_model": "liquidity_aware" if liquidity_config is not None else "fixed_bps",
            "borrow_model": "tiered_adv_assumption" if borrow_config.enabled else "not_applied",
            "neutralize": neutralize_dims,
            "capacity_curve": backtest.capacity_curve,
            "long_short_contribution": backtest.long_short_contribution,
            "neutralization_comparison": neutralization_comparison,
            "parent_run_id": parent_run_id,
            "screen_candidate": candidate["name"],
            "factor_metadata": _factor_metadata(candidate["code"], len(panel)),
        }
        child.save_config(config)
        note = build_cross_sectional_research_note(
            child.run_id,
            config,
            backtest.metrics,
            data_hash,
            ctx.warnings,
            summary,
            ctx.data_quality.to_dict(),
            review_report.to_markdown(),
            ctx.critic_report.to_markdown() if ctx.critic_report else "",
            metrics_ci=_metrics_ci_for_run(child.run_dir),
            ic_significance=backtest.ic_significance.to_dict(),
        )
        child.save_text("research_note.md", note)
        child.save_json("conversation.json", [])
        child.finalize(
            data_hash=data_hash,
            code_hash=code_hash,
            warnings=ctx.warnings,
            model=model,
            critic_model=critic_model,
            conversation_log="conversation.json",
            summary=summary,
            metrics=backtest.metrics,
            review=review_report.to_dict(),
            critic=ctx.critic_report.to_dict() if ctx.critic_report else None,
            parent_run_id=parent_run_id,
            data_slices=_data_slices_from_cache(cache_meta),
            delegations=ctx.delegations,
            sandbox_usage=[asdict(item) for item in ctx.sandbox_usage],
            mcp_calls=ctx.mcp_calls,
            llm_usage=ctx.llm_usage,
        )
        item = _screen_item(candidate["name"], child.run_id, "completed", backtest.metrics, review_report, ctx.critic_report)
        item["_returns"] = backtest.returns
        item["_review_report"] = review_report
        item["_run_dir"] = child.run_dir
        return item
    except Exception as exc:
        child.save_json("error.json", {"traceback": traceback.format_exc()})
        return {
            "name": candidate["name"],
            "run_id": child.run_id,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "verdict": None,
            "critic_verdict": None,
            "critic_agrees": None,
            "sharpe": None,
        }


def _screen_item(
    name: str,
    run_id: str,
    status: str,
    metrics: dict[str, Any],
    review_report: ReviewReport,
    critic_report: CriticReport | None,
) -> dict[str, Any]:
    dsr = _finding_detail(review_report, "deflated_sharpe")
    cpcv = _finding_detail(review_report, "cpcv")
    ic_sig = _finding_detail(review_report, "ic_significance")
    return {
        "name": name,
        "run_id": run_id,
        "status": status,
        "verdict": review_report.verdict,
        "critic_verdict": critic_report.verdict if critic_report else None,
        "critic_agrees": critic_report.agrees_with_deterministic_verdict if critic_report else None,
        "sharpe": metrics.get("sharpe"),
        "dsr": dsr,
        "cpcv": cpcv,
        "ic_significance": ic_sig,
    }


def _finding_detail(review_report: ReviewReport, check: str) -> dict[str, Any] | None:
    for finding in review_report.findings:
        if finding.check == check:
            return finding.detail
    return None


def _public_screen_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _screen_trial_sharpes(items: list[dict[str, Any]]) -> list[float]:
    """Every completed sibling's annualized Sharpe - the empirical cross-trial
    dispersion the DSR needs (deflated_sharpe_ratio de-annualizes internally)."""
    sharpes: list[float] = []
    for item in items:
        if item.get("status") != "completed":
            continue
        sharpe = item.get("sharpe")
        if sharpe is not None and math.isfinite(float(sharpe)):
            sharpes.append(float(sharpe))
    return sharpes


def _screen_pbo(items: list[dict[str, Any]]) -> PBOResult | None:
    columns = {}
    for item in items:
        returns = item.get("_returns")
        if item.get("status") == "completed" and isinstance(returns, pd.Series):
            columns[str(item["name"])] = returns
    if not columns:
        return None
    matrix = pd.DataFrame(columns).sort_index().fillna(0.0)
    return probability_of_backtest_overfitting(matrix)


def _finalize_screen_item(
    item: dict[str, Any],
    trial_sharpes: list[float],
    effective_trials: int,
    pbo_result: PBOResult | None,
) -> None:
    review_report = item.get("_review_report")
    returns = item.get("_returns")
    run_dir = item.get("_run_dir")
    if not isinstance(review_report, ReviewReport) or not isinstance(run_dir, Path):
        return

    # Recompute the DSR finding with the sibling Sharpes now known, and replace
    # the first-pass finding that used only the analytic single-series fallback.
    findings: list[ReviewFinding] = []
    if isinstance(returns, pd.Series):
        dsr_finding = _dsr_finding(returns, effective_trials, trial_sharpes)
        findings = [dsr_finding if f.check == "deflated_sharpe" else f for f in review_report.findings]
    else:
        findings = list(review_report.findings)
    if pbo_result is not None:
        findings.append(_pbo_finding(pbo_result))

    verdict, reason = determine_verdict(findings)
    updated = ReviewReport(findings=findings, verdict=verdict, verdict_reason=reason)
    item["_review_report"] = updated
    item["verdict"] = verdict
    item["dsr"] = _finding_detail(updated, "deflated_sharpe")
    # The Critic ran against the first-pass verdict; re-derive its agreement flag
    # against the final verdict so critic_agrees never points at a stale verdict.
    critic_verdict = item.get("critic_verdict")
    item["critic_agrees"] = (critic_verdict == verdict) if critic_verdict is not None else None

    (run_dir / "review_report.json").write_text(json.dumps(updated.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["review"] = updated.to_dict()
        existing_warnings = list(manifest.get("warnings") or [])
        for message in _review_warning_messages(updated):
            if message not in existing_warnings:
                existing_warnings.append(message)
        manifest["warnings"] = existing_warnings
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _screen_sort_key(item: dict[str, Any]) -> tuple[int, float]:
    verdict_rank = {"STRONG": 4, "PROMISING": 3, "WEAK": 2, "REJECTED": 1}
    sharpe = item.get("sharpe")
    try:
        sharpe_value = float(sharpe)
    except (TypeError, ValueError):
        sharpe_value = float("-inf")
    return (verdict_rank.get(str(item.get("verdict") or ""), 0), sharpe_value)
