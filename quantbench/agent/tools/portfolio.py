import json
from typing import Any

import pandas as pd

from quantbench.agent.helpers.benchmarks import _benchmark_symbol_for_asset
from quantbench.agent.helpers.critic_support import _run_critic_for_context
from quantbench.agent.helpers.research_notes_support import _metrics_ci_for_run, _review_warning_messages
from quantbench.agent.run_context import _RunContext
from quantbench.api import run_reader
from quantbench.artifact.store import ArtifactStore, text_sha256
from quantbench.config import (
    CRITIC_MODEL,
    DEFAULT_COST_BPS,
    PORTFOLIO_DEFAULT_METHOD,
    PORTFOLIO_MAX_FACTORS,
    PORTFOLIO_MAX_WEIGHT,
    PORTFOLIO_MIN_FACTORS,
    PORTFOLIO_MIN_OVERLAP_OBS,
    PORTFOLIO_TRAIN_TEST_SPLIT,
)
from quantbench.engine.metrics import sanity_check_metrics
from quantbench.portfolio.optimize import PORTFOLIO_METHODS
from quantbench.portfolio.pipeline import run_portfolio_pipeline
from quantbench.agent.constants import OPTIMIZE_PORTFOLIO_PARAMS
from quantbench.skills.plot import save_drawdown_plot, save_equity_curve_plot
from quantbench.skills.registry import Skill
from quantbench.skills.report import build_portfolio_research_note


def _run_portfolio_optimization(
    run_store: ArtifactStore,
    critic_llm,
    model: str,
    parent_run_id: str | None,
    run_ids: list[str],
    method: str | None,
    cost_bps: float,
    split: float,
    max_weight: float,
) -> dict[str, Any]:
    """Combines a set of existing runs' own return series into one portfolio
    run. Structurally parallel to _run_screen_candidate: builds its own child
    Run, does the full combine + portfolio-Reviewer + Critic + finalize
    sequence itself, and is called both from the optimize_portfolio tool
    (mid-conversation) and from Coordinator.optimize_portfolio (the CLI/direct
    entry point) - the math and persistence only exist once."""
    if not isinstance(run_ids, list) or not (PORTFOLIO_MIN_FACTORS <= len(run_ids) <= PORTFOLIO_MAX_FACTORS):
        return {"error": f"run_ids must contain between {PORTFOLIO_MIN_FACTORS} and {PORTFOLIO_MAX_FACTORS} run_ids"}

    method = method or PORTFOLIO_DEFAULT_METHOD
    if method not in PORTFOLIO_METHODS:
        return {"error": f"unknown method {method!r}, expected one of {PORTFOLIO_METHODS}"}

    returns_by_run: dict[str, pd.Series] = {}
    asset_classes: set[str] = set()
    unresolved_asset_class: list[str] = []
    for run_id in run_ids:
        series = run_reader.read_returns_series(run_id)
        if series is None or series.empty:
            return {"error": f"run {run_id} has no readable return series (missing or empty backtest_result.json)"}
        returns_by_run[run_id] = series
        asset_class = run_reader.infer_asset_class(run_id)
        # A run whose asset class can't be inferred must NOT be silently
        # dropped from the check - e.g. a legacy/config-less equity run
        # alongside a crypto run would otherwise leave asset_classes = {"crypto"}
        # (the unresolved run contributing nothing) and pass the mismatch gate
        # despite actually mixing equity and crypto data.
        if asset_class is None:
            unresolved_asset_class.append(run_id)
        else:
            asset_classes.add(asset_class)

    if unresolved_asset_class:
        return {
            "error": f"could not determine asset class for run(s): {unresolved_asset_class} - refusing to combine "
            "without being able to verify every run shares the same asset class."
        }
    if len(asset_classes) > 1:
        return {
            "error": f"cannot combine runs across different asset classes: {sorted(asset_classes)} - a covariance "
            "matrix mixing them has no financial meaning."
        }

    aligned_preview = pd.DataFrame(returns_by_run).dropna(how="any")
    if len(aligned_preview) < PORTFOLIO_MIN_OVERLAP_OBS:
        return {
            "error": f"only {len(aligned_preview)} overlapping observations across the requested runs "
            f"(need at least {PORTFOLIO_MIN_OVERLAP_OBS}); combining them is not statistically meaningful."
        }

    asset_class = next(iter(asset_classes), "equity")
    benchmark_symbol = _benchmark_symbol_for_asset(asset_class)
    # _fetch_benchmark_returns stays defined in coordinator.py (it calls
    # fetch_ohlcv, which tests/test_phase5_crypto_universe.py patches as a
    # module attribute on quantbench.agent.coordinator - importing the name
    # directly into this module would silently stop picking up that patch).
    # Deferred import: by the time this function actually runs, coordinator.py
    # (the caller) is already fully loaded, so this isn't a circular import.
    from quantbench.agent import coordinator as coordinator_module

    benchmark_returns = coordinator_module._fetch_benchmark_returns(
        {
            "symbol": benchmark_symbol,
            "timeframe": "4h" if asset_class == "crypto" else "1d",
            "start": str(aligned_preview.index.min().date()),
            "end": str(aligned_preview.index.max().date()),
        },
        None,
    )

    outcome = run_portfolio_pipeline(
        returns_by_run,
        method=method,
        cost_bps=cost_bps,
        split=split,
        max_weight=max_weight,
        benchmark_returns=benchmark_returns,
        benchmark_symbol=benchmark_symbol,
    )

    child = run_store.create_run(f"Optimize portfolio ({method}) from {len(run_ids)} runs: {', '.join(run_ids)}")
    critic_model = str(getattr(critic_llm, "model", CRITIC_MODEL))

    child.save_json("backtest_result.json", outcome.combined.to_json_dict())
    child.save_json("portfolio_weights.json", outcome.weights)
    child.save_json(
        "portfolio_summary.json",
        {
            "parent_run_id": parent_run_id,
            "constituent_run_ids": run_ids,
            "asset_class": asset_class,
            "selected_method": outcome.selected_method,
            "comparison_table": outcome.comparison_table,
            "correlation": outcome.correlation,
            "diversification_ratio": outcome.combined.metrics.get("diversification_ratio"),
            "overlap_observations": outcome.overlap_observations,
            "train_test_split_index": outcome.train_test_split_index,
            "cost_bps": cost_bps,
            "max_weight": max_weight,
        },
    )
    save_equity_curve_plot(outcome.combined.equity_curve, child.run_dir / "equity_curve.png")
    save_drawdown_plot(outcome.combined.drawdown, child.run_dir / "drawdown.png")
    child.save_json("review_report.json", outcome.review_report.to_dict())

    weight_desc = "; ".join(f"{rid}={weight:.2%}" for rid, weight in outcome.weights.items())
    summary = (
        f"Combined {len(run_ids)} factor runs via {outcome.selected_method}: portfolio Sharpe "
        f"{outcome.combined.metrics.get('sharpe')}, diversification ratio "
        f"{outcome.combined.metrics.get('diversification_ratio')}, deterministic verdict "
        f"{outcome.review_report.verdict}. Weights: {weight_desc}."
    )

    ctx = _RunContext()
    ctx.last_metrics = outcome.combined.metrics
    ctx.review_report = outcome.review_report
    ctx.signal_code = json.dumps(
        {"portfolio_method": outcome.selected_method, "weights": outcome.weights, "constituent_run_ids": run_ids},
        indent=2,
    )
    # A near-zero in-sample variance combination (e.g. min_variance finding a
    # fragile near-perfect hedge between two constituents) can mechanically
    # produce an implausible Sharpe even though every number that went into it
    # is individually correct - same failure mode sanity_check_metrics already
    # guards against for single-symbol/cross-sectional runs.
    ctx.warnings.extend(sanity_check_metrics(outcome.combined.metrics))
    ctx.warnings.extend(_review_warning_messages(outcome.review_report))

    _run_critic_for_context(
        ctx,
        child,
        critic_llm,
        summary,
        {
            "asset_class": asset_class,
            "portfolio_method": outcome.selected_method,
            "constituent_run_ids": run_ids,
            "cost_bps": cost_bps,
        },
    )

    config = {
        "hypothesis": f"Portfolio optimization ({outcome.selected_method}) over {len(run_ids)} factor runs",
        "model": model,
        "critic_model": critic_model,
        # Deliberately NOT nested under "universe": library/record.py treats
        # any run with a truthy config["universe"] as cross-sectional, and a
        # portfolio-optimization run is neither a single-symbol nor a
        # cross-sectional backtest - faking a universe here to carry
        # asset_class would mislabel it in the experiment library/API.
        "asset_class": asset_class,
        "parent_run_id": parent_run_id,
        "portfolio_method": outcome.selected_method,
        "constituent_run_ids": run_ids,
    }
    child.save_config(config)

    note = build_portfolio_research_note(
        child.run_id,
        config,
        outcome,
        ctx.warnings,
        summary,
        outcome.review_report.to_markdown(),
        ctx.critic_report.to_markdown() if ctx.critic_report else "",
        metrics_ci=_metrics_ci_for_run(child.run_dir),
    )
    child.save_text("research_note.md", note)
    child.save_json("conversation.json", [])

    data_hash = f"sha256:{text_sha256(json.dumps(sorted(run_ids)))}"
    code_hash = f"sha256:{text_sha256(ctx.signal_code)}"
    child.finalize(
        data_hash=data_hash,
        code_hash=code_hash,
        warnings=ctx.warnings,
        model=model,
        critic_model=critic_model,
        conversation_log="conversation.json",
        summary=summary,
        metrics=outcome.combined.metrics,
        review=outcome.review_report.to_dict(),
        critic=ctx.critic_report.to_dict() if ctx.critic_report else None,
        parent_run_id=parent_run_id,
        delegations=ctx.delegations,
        mcp_calls=ctx.mcp_calls,
        llm_usage=ctx.llm_usage,
    )

    return {
        "run_id": child.run_id,
        "method": outcome.selected_method,
        "weights": outcome.weights,
        "metrics": outcome.combined.metrics,
        "verdict": outcome.review_report.verdict,
        "critic_verdict": ctx.critic_report.verdict if ctx.critic_report else None,
        "critic_agrees": ctx.critic_report.agrees_with_deterministic_verdict if ctx.critic_report else None,
        "comparison_table": {
            m: {"train_sharpe": row["train_sharpe"], "test_sharpe": row["test_sharpe"]}
            for m, row in outcome.comparison_table.items()
        },
        "warnings": ctx.warnings,
        "summary": summary,
    }


def build_optimize_portfolio_skill(run_store: ArtifactStore, critic_llm, model: str, run) -> Skill:
    def _optimize_portfolio(
        run_ids: list[str],
        method: str | None = None,
        cost_bps: float = DEFAULT_COST_BPS,
        split: float = PORTFOLIO_TRAIN_TEST_SPLIT,
        max_weight: float = PORTFOLIO_MAX_WEIGHT,
    ) -> dict:
        return _run_portfolio_optimization(
            run_store, critic_llm, model, run.run_id, run_ids, method, cost_bps, split, max_weight
        )

    return Skill(
        "optimize_portfolio",
        "Combine multiple existing runs' own factors into one multi-factor portfolio with fitted weights.",
        OPTIMIZE_PORTFOLIO_PARAMS,
        _optimize_portfolio,
    )
