import json
import math
import os
import threading
from quantbench.agent.execution_backend import get_execution_backend
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from quantbench.agent.llm import LLMClient
from quantbench.agent.prompts import SYSTEM_PROMPT
from quantbench.artifact.store import ArtifactStore
from quantbench.config import CRITIC_MODEL, DEFAULT_COST_BPS, DEFAULT_MODEL, MCP_SERVERS_CONFIG, MODEL_ENV, RUNS_DIR
from quantbench.config import (
    PORTFOLIO_MAX_WEIGHT,
    PORTFOLIO_TRAIN_TEST_SPLIT,
)
from quantbench.config import SCREEN_MAX_CANDIDATES, SCREEN_MAX_WORKERS
from quantbench.config import SKILL_DOCS_DIR as DEFAULT_SKILL_DOCS_DIR
from quantbench.data.cache import file_sha256
from quantbench.data.exchange import SYNTHETIC_FALLBACK_SOURCE, fetch_ohlcv
from quantbench.data.universe import apply_covers_delisted, build_universe
from quantbench.data.warehouse import fetch_universe_funding_rates, fetch_universe_ohlcv
from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest
from quantbench.engine.execution import ExecutionConfig
from quantbench.engine.metrics import sanity_check_metrics
from quantbench.review import run_review
from quantbench.factors.parametrize import apply_overrides
from quantbench.factors.store import FactorStore
from quantbench.agent.staging import CostEstimate, StagingGate, StagingPolicy
from quantbench.library.aggregate import summarize as summarize_library
from quantbench.library.fork import build_fork_config
from quantbench.library.index import ExperimentIndex
from quantbench.memory.defaults import apply_memory_defaults, merge_applied_memory_defaults
from quantbench.memory.inject import build_memory_augmented_system_prompt
from quantbench.memory.store import UserMemoryStore
from quantbench.library.trials import count_trials, universe_signature
from quantbench.skilldocs.inject import build_augmented_system_prompt
from quantbench.skilldocs.registry import SkillRegistryDocs
from quantbench.skills.codeexec import run_signal_code_panel
from quantbench.skills.data_quality import validate_universe_data
from quantbench.skills.mcp_adapter import MCPClientManager, load_mcp_config
from quantbench.skills.plot import (
    save_drawdown_plot,
    save_equity_curve_plot,
    save_group_returns_plot,
    save_ic_plot,
    save_risk_attribution_plot,
)
from quantbench.skills.registry import Skill, SkillRegistry
from quantbench.skills.report import build_cross_sectional_research_note, build_research_note

from quantbench.agent.constants import (
    BUILD_UNIVERSE_PARAMS,
    CHECK_RUN_DECAY_PARAMS,
    FETCH_OHLCV_PARAMS,
    RUN_CROSS_SECTIONAL_BACKTEST_PARAMS,
    SCREEN_FACTORS_PARAMS,
    SIGNAL_FILE_HARNESS,
    SIGNAL_FILE_HEADER,
)
# RunCancelled is re-exported here (unused within this module's own body) so
# that quantbench/api/run_manager.py's `from quantbench.agent.coordinator
# import Coordinator, RunCancelled` keeps working unchanged.
from quantbench.agent.run_context import RunCancelled, RunResult, _RunContext
from quantbench.agent.helpers.config_normalizers import (
    _borrow_cost_config,
    _borrow_rates_for_panel,
    _execution_config,
    _liquidity_cost_config,
    _neutralize_dimensions,
    _sector_series,
)
from quantbench.agent.helpers.sensitivity import (
    _cross_execution_sensitivity,
    _metrics_without_borrow,
    _neutralization_comparison,
)
from quantbench.agent.helpers.benchmarks import (
    _benchmark_symbol_for_asset,
    _is_crypto_universe,
)
from quantbench.agent.helpers.research_notes_support import (
    _append_crypto_perpetual_warning,
    _backtest_payload_with_factor_metadata,
    _data_slices_from_cache,
    _factor_metadata,
    _fork_lineage_markdown,
    _ic_significance_for_run,
    _metrics_ci_for_run,
    _rerun_cross_with_code,
    _review_warning_messages,
)
from quantbench.agent.helpers.critic_support import _critic_context, _run_critic_for_context
from quantbench.agent.loop import _message_to_dict, run_agent_loop
from quantbench.agent.tools.screening import (
    _finalize_screen_item,
    _public_screen_item,
    _run_screen_candidate,
    _screen_pbo,
    _screen_sort_key,
    _screen_trial_sharpes,
)
from quantbench.agent.tools.portfolio import _run_portfolio_optimization, build_optimize_portfolio_skill
from quantbench.agent.tools.backtest_single import build_fork_run_signal_backtest_skill, build_run_signal_backtest_skill
from quantbench.agent.tools.monitor import _check_run_decay


def build_fetch_ohlcv_skill(ctx: _RunContext) -> Skill:
    def _fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> dict:
        data_path, data_df, cache_meta = fetch_ohlcv(symbol, timeframe, start, end)
        ctx.data_path, ctx.data_df, ctx.cache_meta = data_path, data_df, cache_meta
        ctx.fetch_params = {"symbol": symbol, "timeframe": timeframe, "start": start, "end": end}

        if cache_meta.get("source") == SYNTHETIC_FALLBACK_SOURCE:
            ctx.warnings.append(
                "DATA IS SYNTHETIC, NOT REAL MARKET DATA. Real data fetch failed "
                f"({cache_meta.get('fallback_reason')}); every downstream metric is "
                "meaningless for real trading decisions."
            )
        elif cache_meta.get("source") == "unknown_legacy_cache":
            ctx.warnings.append(
                "Cached data has no provenance metadata (cached before source tracking "
                "existed). Delete data_cache/ and re-run to confirm real vs synthetic."
            )

        return {
            "rows": len(data_df),
            "start": str(data_df["timestamp"].iloc[0]) if len(data_df) else None,
            "end": str(data_df["timestamp"].iloc[-1]) if len(data_df) else None,
            "source": cache_meta.get("source"),
            "cache_hit": cache_meta.get("cache_hit"),
        }
    return Skill("fetch_ohlcv", "Fetch and cache OHLCV market data.", FETCH_OHLCV_PARAMS, _fetch_ohlcv)


# build_universe / run_cross_sectional_backtest / screen_factors call
# build_universe, fetch_universe_ohlcv, and _fetch_benchmark_returns, which
# tests/test_phase5_crypto_universe.py and tests/test_phase8_factor_screening.py
# patch as module attributes on quantbench.agent.coordinator (not via a
# dotted-string monkeypatch, which would tolerate relocation). Moving these
# three builders into quantbench/agent/tools/ would silently stop those test
# patches from taking effect, since a Python closure resolves free variables
# against the module it is defined in, not the module it was imported into.
# They stay here as top-level builder functions - not nested closures inside
# _build_registry - so that function itself is still pure composition.


def build_build_universe_skill(ctx: _RunContext, run) -> Skill:
    def _build_universe(
        universe_name: str,
        as_of_date: str,
        point_in_time: bool = False,
        limit: int | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        try:
            kwargs: dict[str, Any] = {"point_in_time": point_in_time, "limit": limit}
            if start is not None:
                kwargs["start"] = start
            if end is not None:
                kwargs["end"] = end
            universe = build_universe(universe_name, as_of_date, **kwargs)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        ctx.universe = universe
        run.save_text("universe.yaml", __import__("yaml").safe_dump(universe.to_dict(), sort_keys=False, allow_unicode=True))
        ctx.warnings.append(universe.survivorship_bias_note)
        return {
            "name": universe.name,
            "as_of_date": universe.as_of_date,
            "symbols": len(universe.symbols),
            "point_in_time": universe.point_in_time,
            "sample_limit": universe.sample_limit,
            "asset_class": universe.asset_class,
            "membership_intervals": universe.membership_intervals,
            "covers_delisted": universe.covers_delisted,
            "survivorship_bias_note": universe.survivorship_bias_note,
            "source": universe.source,
        }
    return Skill(
        "build_universe", "Build a named equity universe such as the current S&P 500.", BUILD_UNIVERSE_PARAMS, _build_universe
    )


def build_run_cross_sectional_backtest_skill(ctx: _RunContext, run) -> Skill:
    def _run_cross_sectional_backtest(
        code: str,
        start: str,
        end: str,
        timeframe: str = "1d",
        n_groups: int = 10,
        cost_bps: float = DEFAULT_COST_BPS,
        execution: dict[str, str] | None = None,
        liquidity_cost: dict[str, Any] | None = None,
        borrow_cost: dict[str, Any] | None = None,
        neutralize: list[str] | None = None,
    ) -> dict:
        if ctx.screened:
            return {
                "error": "screen_factors already produced final, complete results for this session "
                "(backtest + Reviewer + Critic per candidate). Do not re-run individual backtests to "
                "re-verify or spot-check - report the screen_factors result directly in your final answer."
            }
        if ctx.universe is None:
            return {"error": "no universe loaded yet - call build_universe first"}

        panel, cache_meta = fetch_universe_ohlcv(ctx.universe, timeframe, start, end)
        ctx.universe = apply_covers_delisted(ctx.universe, cache_meta)
        funding_rates = None
        funding_meta = None
        if _is_crypto_universe(ctx.universe):
            funding_rates, funding_meta = fetch_universe_funding_rates(ctx.universe, start, end)
            ctx.funding_df = funding_rates
            ctx.funding_meta = funding_meta
        ctx.panel_df = panel
        ctx.cache_meta = cache_meta
        ctx.data_quality = validate_universe_data(panel, ctx.universe, end=end)
        ctx.cross_sectional = True

        if ctx.data_quality.symbols_missing_entirely:
            ctx.warnings.append(
                f"{len(ctx.data_quality.symbols_missing_entirely)} universe symbols have no data and were excluded."
            )
        if ctx.data_quality.symbols_with_gaps:
            ctx.warnings.append(f"{len(ctx.data_quality.symbols_with_gaps)} symbols have missing business-day gaps.")
        if ctx.data_quality.suspicious_price_jumps:
            ctx.warnings.append(
                f"{len(ctx.data_quality.suspicious_price_jumps)} symbols have >50% one-period price jumps."
            )

        factor_values = run_signal_code_panel(code, panel, usage_sink=ctx.sandbox_usage)
        config, applied_defaults = apply_memory_defaults(
            {
                "start": start,
                "end": end,
                "timeframe": timeframe,
                "n_groups": n_groups,
                "cost_bps": cost_bps,
                "execution": execution,
                "liquidity_cost": liquidity_cost,
                "borrow_cost": borrow_cost,
                "neutralize": neutralize,
            },
            ctx.memory_default_facts,
        )
        ctx.applied_memory_defaults = merge_applied_memory_defaults(ctx.applied_memory_defaults, applied_defaults)
        staged = StagingGate(
            run_id=run.run_id,
            run_dir=run.run_dir,
            policy=StagingPolicy(force_stage=bool(applied_defaults)),
            confirm_callback=ctx.staging_confirm,
        ).review(
            code=code,
            factor_values=factor_values,
            config=config,
            cost=CostEstimate(
                kind="cross_sectional",
                observations=len(panel),
                symbols=panel["symbol"].nunique() if "symbol" in panel.columns else None,
            ),
            hypothesis="cross-sectional factor",
            available_columns=list(panel.columns),
            data_quality=ctx.data_quality,
        )
        ctx.staging = staged.artifact
        code = staged.code
        n_groups = staged.config.get("n_groups", n_groups)
        cost_bps = staged.config.get("cost_bps", cost_bps)
        execution = staged.config.get("execution", execution)
        liquidity_cost = staged.config.get("liquidity_cost", liquidity_cost)
        borrow_cost = staged.config.get("borrow_cost", borrow_cost)
        neutralize = staged.config.get("neutralize", neutralize)
        if staged.code_changed:
            factor_values = run_signal_code_panel(code, panel, usage_sink=ctx.sandbox_usage)
        execution_config = _execution_config(execution)
        liquidity_config = _liquidity_cost_config(liquidity_cost)
        borrow_config = _borrow_cost_config(borrow_cost)
        borrow_rates = _borrow_rates_for_panel(panel, borrow_config)
        neutralize_dims = _neutralize_dimensions(neutralize)
        sector = _sector_series(ctx.universe)
        backtest = run_cross_sectional_backtest(
            panel,
            None,
            n_groups=n_groups,
            cost_bps=cost_bps,
            membership_intervals=ctx.universe.membership_intervals,
            funding_rates=funding_rates,
            execution=execution_config,
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
                membership_intervals=ctx.universe.membership_intervals,
                execution=execution_config,
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
            ctx.funding_meta = funding_meta

        ctx.signal_code = code
        ctx.last_metrics = backtest.metrics
        ctx.cost_bps = cost_bps
        ctx.execution = execution_config
        ctx.cost_model = "liquidity_aware" if liquidity_config is not None else "fixed_bps"
        ctx.borrow_model = "tiered_adv_assumption" if borrow_config.enabled else "not_applied"
        ctx.neutralize = neutralize_dims
        ctx.capacity_curve = backtest.capacity_curve
        ctx.long_short_contribution = backtest.long_short_contribution
        ctx.neutralization_comparison = _neutralization_comparison(
            panel,
            factor_values,
            n_groups,
            cost_bps,
            ctx.universe.membership_intervals,
            funding_rates,
            execution_config,
            liquidity_config,
            borrow_rates,
            neutralize_dims,
            sector,
        )
        panel_path = run.run_dir / "panel.parquet"
        panel.to_parquet(panel_path, index=False)
        run.save_code("signal.py", SIGNAL_FILE_HEADER + code + SIGNAL_FILE_HARNESS)
        # Same filename as the single-symbol path (not "cross_sectional_backtest_result.json" -
        # that name drifted from the single-symbol path's and matches nothing else in the
        # codebase or README's documented artifact layout; readers like ChartsPanel and
        # library/compare.py's compute_returns_correlation() look for one canonical name).
        run.save_json("backtest_result.json", _backtest_payload_with_factor_metadata(backtest, code, len(panel)))
        run.save_json("data_quality_report.json", ctx.data_quality.to_dict())
        save_equity_curve_plot(backtest.equity_curve, run.run_dir / "equity_curve.png")
        save_drawdown_plot(backtest.drawdown, run.run_dir / "drawdown.png")
        save_group_returns_plot(backtest.group_returns, run.run_dir / "group_returns.png")
        save_ic_plot(backtest.ic_series, run.run_dir / "rank_ic.png")
        if ctx.neutralization_comparison:
            save_risk_attribution_plot(ctx.neutralization_comparison, run.run_dir / "risk_attribution.png")

        new_warnings = _append_crypto_perpetual_warning(ctx) if _is_crypto_universe(ctx.universe) else []
        new_warnings.extend(sanity_check_metrics(backtest.metrics))
        benchmark_symbol = _benchmark_symbol_for_asset(ctx.universe.asset_class)
        review_report = run_review(
            code=code,
            returns=backtest.returns,
            cost_bps=cost_bps,
            rerun_at_cost=lambda bps: run_cross_sectional_backtest(
                panel,
                None,
                n_groups=n_groups,
                cost_bps=bps,
                membership_intervals=ctx.universe.membership_intervals,
                funding_rates=funding_rates,
                execution=execution_config,
                liquidity_cost_config=liquidity_config,
                borrow_rates=borrow_rates,
                neutralize=neutralize_dims,
                sector=sector,
                factor_values=factor_values,
            ).metrics,
            rerun_with_code=lambda candidate: _rerun_cross_with_code(
                candidate, panel, n_groups, cost_bps, ctx.universe.membership_intervals
            ),
            out_of_sample_data=panel,
            run_on_data=lambda data: _rerun_cross_with_code(
                code, data, n_groups, cost_bps, ctx.universe.membership_intervals
            ) or {},
            benchmark_returns=_fetch_benchmark_returns(
                {"symbol": benchmark_symbol, "timeframe": timeframe, "start": start, "end": end}, None
            ),
            benchmark_symbol=benchmark_symbol,
            factor_panel=backtest.factor_panel,
            n_groups=n_groups,
            turnover_annual=backtest.metrics.get("turnover_annual"),
            universe_coverage=(cache_meta.get("coverage_report") if isinstance(cache_meta, dict) else None),
            funding_cost_sensitivity=funding_sensitivity,
            execution_sensitivity=_cross_execution_sensitivity(
                panel,
                factor_values,
                n_groups,
                cost_bps,
                ctx.universe.membership_intervals,
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
                    ctx.universe.membership_intervals,
                    funding_rates,
                    execution_config,
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
            execution=execution_config.to_dict(),
            universe=ctx.universe.to_dict(),
        )
        ctx.review_report = review_report
        run.save_json("review_report.json", review_report.to_dict())
        review_warnings = _review_warning_messages(review_report)
        new_warnings.extend(review_warnings)
        ctx.warnings.extend(new_warnings)

        return {
            **backtest.metrics,
            "data_quality": ctx.data_quality.to_dict(),
            "cache": cache_meta,
            "funding": funding_meta,
            "warnings": new_warnings,
            "review": review_report.to_dict(),
        }
    return Skill(
        "run_cross_sectional_backtest",
        "Fetch a universe panel, run causal factor code per symbol, and backtest equal-weight factor groups.",
        RUN_CROSS_SECTIONAL_BACKTEST_PARAMS,
        _run_cross_sectional_backtest,
    )


def build_screen_factors_skill(ctx: _RunContext, run, run_store: ArtifactStore, critic_llm, model: str) -> Skill:
    def _screen_factors(
        candidates: list[dict[str, str]],
        start: str,
        end: str,
        timeframe: str = "1d",
        n_groups: int = 10,
        cost_bps: float = DEFAULT_COST_BPS,
        execution: dict[str, str] | None = None,
        liquidity_cost: dict[str, Any] | None = None,
        borrow_cost: dict[str, Any] | None = None,
        neutralize: list[str] | None = None,
    ) -> dict:
        if ctx.universe is None:
            return {"error": "no universe loaded yet - call build_universe first"}
        if not isinstance(candidates, list) or not (1 <= len(candidates) <= SCREEN_MAX_CANDIDATES):
            return {"error": f"candidates must contain between 1 and {SCREEN_MAX_CANDIDATES} items"}

        normalized = []
        for index, candidate in enumerate(candidates):
            name = str(candidate.get("name") or f"candidate_{index + 1}")
            code = str(candidate.get("code") or "")
            if not code.strip():
                return {"error": f"candidate {name} has empty code"}
            normalized.append({"name": name, "code": code})

        panel, cache_meta = fetch_universe_ohlcv(ctx.universe, timeframe, start, end)
        ctx.universe = apply_covers_delisted(ctx.universe, cache_meta)
        funding_rates = None
        funding_meta = None
        if _is_crypto_universe(ctx.universe):
            funding_rates, funding_meta = fetch_universe_funding_rates(ctx.universe, start, end)
        # Fetched once up front rather than per-candidate: all candidates share the same
        # universe/date range/timeframe, so the benchmark series is identical for every
        # one of them. Fetching it once also avoids N threads racing an identical
        # cache-miss fetch and avoids a transient fetch failure giving some candidates a
        # beta check against real data and others against none.
        benchmark_symbol = _benchmark_symbol_for_asset(ctx.universe.asset_class)
        benchmark_returns = _fetch_benchmark_returns(
            {"symbol": benchmark_symbol, "timeframe": timeframe, "start": start, "end": end}, None
        )
        signature = universe_signature(ctx.universe.to_dict())
        trial_count = count_trials(signature, start, end)
        effective_trials = len(normalized) + trial_count.prior_trials
        liquidity_config = _liquidity_cost_config(liquidity_cost)
        borrow_config = _borrow_cost_config(borrow_cost)
        borrow_rates = _borrow_rates_for_panel(panel, borrow_config)
        neutralize_dims = _neutralize_dimensions(neutralize)
        sector = _sector_series(ctx.universe)
        execution_config = _execution_config(execution)
        # GAP 5.4: surfaced in the returned payload before the (expensive) fan-out below
        # runs, so the caller sees the cost shape up front. Purely informational - this
        # does not add a new blocking gate; each candidate's own cross-sectional backtest
        # still goes through its own per-candidate StagingGate (1.4) independently.
        cost_estimate = asdict(
            CostEstimate(kind="screen", observations=len(panel), candidates=len(normalized))
        )
        cost_estimate["estimated_critic_delegations"] = len(normalized)

        def _screen_one(candidate: dict[str, Any]) -> dict[str, Any]:
            return _run_screen_candidate(
                run_store,
                critic_llm,
                model,
                run.run_id,
                ctx.universe,
                panel,
                cache_meta,
                funding_rates,
                funding_meta,
                candidate,
                start,
                end,
                timeframe,
                n_groups,
                cost_bps,
                execution_config,
                liquidity_config,
                borrow_config,
                borrow_rates,
                neutralize_dims,
                sector,
                benchmark_returns,
                effective_trials,
            )

        summary_items = get_execution_backend().map(_screen_one, normalized, max_workers=SCREEN_MAX_WORKERS)

        # Second pass: now that every sibling candidate's Sharpe is known, the
        # DSR can finally use the *cross-trial* Sharpe dispersion (its whole
        # point) instead of the single-series analytic fallback used in the
        # per-candidate first pass, and the batch-level PBO can be folded in.
        # Both re-derive the verdict, so they must happen together here rather
        # than inside the parallel per-candidate review.
        trial_sharpes = _screen_trial_sharpes(summary_items)
        pbo_result = _screen_pbo(summary_items)
        for item in summary_items:
            if item.get("status") == "completed":
                _finalize_screen_item(item, trial_sharpes, effective_trials, pbo_result)
        summary_items.sort(key=_screen_sort_key, reverse=True)
        public_items = [_public_screen_item(item) for item in summary_items]
        payload = {
            "parent_run_id": run.run_id,
            "universe": ctx.universe.to_dict(),
            "universe_signature": signature,
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "n_groups": n_groups,
            "cost_bps": cost_bps,
            "execution": _execution_config(execution).to_dict(),
            "cost_model": "liquidity_aware" if liquidity_config is not None else "fixed_bps",
            "borrow_model": "tiered_adv_assumption" if borrow_config.enabled else "not_applied",
            "neutralize": neutralize_dims,
            "effective_trials": effective_trials,
            "cost_estimate": cost_estimate,
            "trial_count": asdict(trial_count),
            "pbo": asdict(pbo_result) if pbo_result is not None else None,
            "critic_model": str(getattr(critic_llm, "model", CRITIC_MODEL)),
            "candidates": public_items,
        }
        run.save_json("factor_screen_summary.json", payload)
        ctx.screened = True
        return payload
    return Skill(
        "screen_factors",
        "Batch-screen multiple causal cross-sectional factor candidates against the current universe.",
        SCREEN_FACTORS_PARAMS,
        _screen_factors,
    )


READ_SKILL_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "skill": {"type": "string", "description": "Injected Skill name."},
        "path": {"type": "string", "description": "Relative attached file path inside that Skill directory."},
    },
    "required": ["skill", "path"],
}


FORK_PREVIOUS_RUN_PARAMS = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Existing run_id selected from the current session context."},
        "modification": {"type": "string", "description": "Requested change to apply to the selected parent run."},
    },
    "required": ["run_id", "modification"],
}


def build_fork_previous_run_skill(execute_fork_callback: Callable[[str, str], str]) -> Skill:
    def _fork_previous_run(run_id: str, modification: str) -> dict[str, str]:
        child_run_id = execute_fork_callback(run_id, modification)
        return {"run_id": child_run_id, "parent_run_id": run_id}

    return Skill(
        "fork_previous_run",
        "Fork a previous run from this session by explicit run_id and rerun it with a modification.",
        FORK_PREVIOUS_RUN_PARAMS,
        _fork_previous_run,
    )


def build_read_skill_file_skill(docs_dir: Path = DEFAULT_SKILL_DOCS_DIR) -> Skill:
    def _read_skill_file(skill: str, path: str) -> dict[str, str]:
        try:
            doc = SkillRegistryDocs(docs_dir).get(skill)
            skill_path = Path(doc.path)
            if skill_path.name != "SKILL.md":
                return {"error": f"skill {skill} has no attachment directory"}
            skill_dir = skill_path.parent.resolve()
            requested = (skill_dir / path).resolve()
            try:
                requested.relative_to(skill_dir)
            except ValueError:
                return {"error": "requested path is outside skill directory"}
            if not requested.is_file():
                return {"error": f"skill file not found: {path}"}
            return {"skill": skill, "path": path, "content": requested.read_text(encoding="utf-8")}
        except Exception as exc:  # noqa: BLE001 - tools report structured errors to the agent loop
            return {"error": f"{type(exc).__name__}: {exc}"}

    return Skill(
        "read_skill_file",
        "Read an attached file from an injected directory-style Skill. Path must stay inside that Skill directory.",
        READ_SKILL_FILE_PARAMS,
        _read_skill_file,
    )


def _build_registry(
    ctx: _RunContext,
    run,
    run_store: ArtifactStore,
    critic_llm,
    model: str,
    mcp_manager: MCPClientManager | None = None,
    fork_previous_run_callback: Callable[[str, str], str] | None = None,
) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(build_fetch_ohlcv_skill(ctx))
    registry.register(build_run_signal_backtest_skill(ctx, run))
    registry.register(build_build_universe_skill(ctx, run))
    registry.register(build_run_cross_sectional_backtest_skill(ctx, run))
    registry.register(build_screen_factors_skill(ctx, run, run_store, critic_llm, model))
    registry.register(build_read_skill_file_skill(DEFAULT_SKILL_DOCS_DIR))
    if fork_previous_run_callback is not None:
        registry.register(build_fork_previous_run_skill(fork_previous_run_callback))
    registry.register(build_optimize_portfolio_skill(run_store, critic_llm, model, run))
    registry.register(
        Skill(
            "check_run_decay",
            "Check whether an existing STRONG/PROMISING run's performance has decayed since it was created, "
            "using freshly fetched market data.",
            CHECK_RUN_DECAY_PARAMS,
            _check_run_decay,
        )
    )
    if mcp_manager is not None:
        for skill in mcp_manager.build_skills():
            registry.register(skill)
    return registry


def _build_fork_registry(ctx: _RunContext, run) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(build_fork_run_signal_backtest_skill(ctx, run))
    return registry


class Coordinator:
    def __init__(
        self,
        model: str | None = None,
        run_store: ArtifactStore | None = None,
        llm: LLMClient | None = None,
        critic_llm: LLMClient | None = None,
        memory_store: UserMemoryStore | None = None,
    ):
        self.model = model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        self.run_store = run_store or ArtifactStore(RUNS_DIR)
        self.llm = llm or LLMClient(self.model)
        # Falls back to whichever model the user just configured (self.model),
        # not the hardcoded default, so switching provider from the Web UI
        # covers the Critic too unless QUANTBENCH_CRITIC_MODEL explicitly pins it.
        self.critic_llm = critic_llm or LLMClient(os.environ.get("QUANTBENCH_CRITIC_MODEL", self.model))
        self.critic_model = str(getattr(self.critic_llm, "model", CRITIC_MODEL))
        self._mcp_configs = load_mcp_config(MCP_SERVERS_CONFIG)
        self.memory_store = memory_store or UserMemoryStore()

    def run(self, user_request: str, *, skill_names: list[str] | None = None) -> RunResult:
        run = self.run_store.create_run(user_request)
        return self.execute(run, user_request, skill_names=skill_names)

    def run_from_factor(
        self,
        factor_name: str,
        param_overrides: dict[str, str] | None,
        request: str,
        *,
        skill_names: list[str] | None = None,
        factor_store: FactorStore | None = None,
    ) -> RunResult:
        store = factor_store or FactorStore()
        factor = store.load_factor(factor_name)
        code = apply_overrides(factor.code, param_overrides or {})
        limitations = "\n".join(
            f"- {finding.get('severity')} [{finding.get('check')}]: {finding.get('message')}"
            for finding in factor.source_findings
        ) or "- none recorded"
        seed_request = (
            f"Use factor-library entry `{factor.name}` as the starting point for this run.\n"
            f"Source run: {factor.source_run_id}; source verdict: {factor.source_verdict}.\n"
            f"Known limitations from reviewer findings:\n{limitations}\n\n"
            "Starting signal code after requested parameter overrides:\n"
            f"```python\n{code}\n```\n\n"
            "Run the normal QuantBench workflow for this new request. You may revise the code if the new data or scenario requires it.\n"
            f"User request: {request}"
        )
        run = self.run_store.create_run(f"Factor {factor_name}: {request}")
        return self.execute(
            run,
            request,
            skill_names=skill_names,
            derived_from_factor=factor_name,
            prompt_override=seed_request,
        )

    def run_from_paper(
        self,
        paper_id: str,
        request: str | None = None,
        *,
        focus: str | None = None,
        skill_names: list[str] | None = None,
        paper_store: "PaperStore | None" = None,
    ) -> RunResult:
        """Direct (non-conversational) entry point for `quantbench literature
        reproduce`. Creates the Run, then delegates to execute_from_paper -
        same run()/execute() split the rest of the coordinator uses, so the web
        API (which needs the run_id before the work finishes) can create the
        Run itself and call execute_from_paper directly."""
        run = self.run_store.create_run(f"Reproduce paper {paper_id}: {request or ''}".strip())
        return self.execute_from_paper(
            run, paper_id, request, focus=focus, skill_names=skill_names, paper_store=paper_store
        )

    def execute_from_paper(
        self,
        run,
        paper_id: str,
        request: str | None = None,
        *,
        focus: str | None = None,
        skill_names: list[str] | None = None,
        paper_store: "PaperStore | None" = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
        staging_confirm: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> RunResult:
        """Literature reproduction pipeline (GAP 4.3). Reads a paper with the
        Literature Agent (the 4th SubAgent), distills one factor, then runs the
        NORMAL QuantBench workflow via execute() with a seed prompt - exactly
        like run_from_factor, but seeded from a paper instead of a saved factor.
        After the run, writes a reproduction_comparison.json artifact diffing the
        paper's reported numbers against what we actually measured, and appends
        that table to the research note.

        `focus`, if given (e.g. a highlighted PDF selection from the web UI),
        narrows the extraction to that passage."""
        from quantbench.literature.agent import extract_factor
        from quantbench.literature.reproduction import (
            build_reproduction_comparison,
            render_comparison_markdown,
        )
        from quantbench.literature.store import PaperStore

        store = paper_store or PaperStore()
        paper = store.load(paper_id)

        extraction_usage: list[dict[str, Any]] = []
        extraction = extract_factor(self.llm, paper, focus=focus, usage_sink=extraction_usage)
        lit_source = paper.literature_source(extraction.page_anchors)

        clean_request = request or f"复现论文《{paper.title}》中的因子 `{extraction.factor_name}`。"
        caveats = "\n".join(f"- {item}" for item in extraction.known_caveats) or "- none recorded"
        assumptions = "\n".join(f"- {item}" for item in extraction.assumptions) or "- none recorded"
        reported = json.dumps(extraction.reported_results or {}, ensure_ascii=False)
        seed_request = (
            f"Reproduce a factor distilled from the paper: {paper.citation()}\n"
            f"Factor name: {extraction.factor_name}\n"
            f"Economic hypothesis (why this should be alpha):\n{extraction.economic_hypothesis}\n\n"
            f"Formula:\n{extraction.formula}\n\n"
            f"How to implement compute(df) (df has open/high/low/close/volume):\n{extraction.compute_spec}\n\n"
            f"Suggested universe: {extraction.suggested_universe or 'use your judgement'}; "
            f"timeframe: {extraction.suggested_timeframe or 'use your judgement'}; "
            f"asset class: {extraction.asset_class or 'unknown'}; "
            f"direction: {extraction.direction or 'long_high'}.\n"
            f"Paper's reported results (for later comparison, do NOT hardcode): {reported}\n"
            f"Assumptions (paper left these unspecified):\n{assumptions}\n"
            f"Known caveats:\n{caveats}\n\n"
            "Implement compute() per the spec and run the normal QuantBench workflow "
            "(fetch data, build universe if cross-sectional, backtest, review). You may adapt "
            "the implementation if the data or scenario requires it.\n"
            f"User request: {clean_request}"
        )

        run.save_json("factor_extraction.json", extraction.to_dict())
        result = self.execute(
            run,
            clean_request,
            skill_names=skill_names,
            prompt_override=seed_request,
            literature_source=lit_source,
            extra_llm_usage=extraction_usage,
            on_event=on_event,
            cancel_event=cancel_event,
            staging_confirm=staging_confirm,
        )

        comparison = build_reproduction_comparison(extraction, result.metrics, literature_source=lit_source)
        run.save_json("reproduction_comparison.json", comparison)
        note_path = run.run_dir / "research_note.md"
        if note_path.exists():
            existing = note_path.read_text(encoding="utf-8")
            note_path.write_text(existing + "\n\n" + render_comparison_markdown(comparison), encoding="utf-8")
        return result

    def run_fork(self, parent_run_id: str, modification_request: str) -> RunResult:
        run = self.run_store.create_run(f"Fork {parent_run_id}: {modification_request}")
        return self.execute_fork(run, parent_run_id, modification_request)

    def optimize_portfolio(
        self,
        run_ids: list[str],
        method: str | None = None,
        cost_bps: float | None = None,
        split: float | None = None,
        max_weight: float | None = None,
    ) -> RunResult:
        """Direct (non-conversational) entry point for `quantbench portfolio optimize`
        - shares _run_portfolio_optimization with the optimize_portfolio tool
        used inside execute()'s tool-use loop, so the CLI and the LLM-driven
        path can never produce different combination logic."""
        result = _run_portfolio_optimization(
            self.run_store,
            self.critic_llm,
            self.model,
            None,
            run_ids,
            method,
            cost_bps if cost_bps is not None else DEFAULT_COST_BPS,
            split if split is not None else PORTFOLIO_TRAIN_TEST_SPLIT,
            max_weight if max_weight is not None else PORTFOLIO_MAX_WEIGHT,
        )
        if "error" in result:
            raise ValueError(result["error"])
        return RunResult(
            run_id=result["run_id"],
            run_dir=self.run_store.runs_dir / result["run_id"],
            metrics=result["metrics"],
            warnings=result["warnings"],
            summary=result["summary"],
        )

    def execute(
        self,
        run,
        user_request: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        parent_run_id: str | None = None,
        skill_names: list[str] | None = None,
        derived_from_factor: str | None = None,
        prompt_override: str | None = None,
        cancel_event: threading.Event | None = None,
        staging_confirm: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None,
        session_context: str | None = None,
        session_id: str | None = None,
        turn_index: int | None = None,
        literature_source: dict[str, Any] | None = None,
        extra_llm_usage: list[dict[str, Any]] | None = None,
    ) -> RunResult:
        """Drive the tool-use loop for an already-created Run.

        Split out from `run()` so callers that need the run_id before execution
        finishes (e.g. the web API, which returns run_id immediately and runs
        the loop in a background thread) can call `run_store.create_run(...)`
        themselves first, then hand the Run object here.

        `on_event`, if given, is called synchronously with a small dict at each
        step (tool call start/end, final answer) - purely an observation hook
        for live progress streaming (see quantbench/api). It never influences
        the loop's own logic or control flow.

        `prompt_override`, if given, replaces `user_request` only as the
        content of the first LLM message (e.g. run_from_factor's seed prompt,
        which embeds reference code and reviewer findings). `user_request`
        itself stays the clean human request text everywhere else - it's what
        `config.yaml`'s `hypothesis` records, what the experiment library's
        factor_family classifier reads, and what Skill matching runs against.
        Matching Skills against a prompt stuffed with factor code and finding
        text would risk spurious keyword hits unrelated to the user's actual
        intent, and "hypothesis" showing a code blob instead of the request
        would make the experiment library unreadable.
        """

        def emit(event: dict[str, Any]) -> None:
            if on_event is not None:
                on_event(event)

        if _is_library_question(user_request):
            return self._execute_library_question(run, user_request, emit, session_id=session_id, turn_index=turn_index)

        ctx = _RunContext()
        ctx.staging_confirm = staging_confirm
        # Literature extraction (run_from_paper) happens before this ctx exists;
        # seed its LLM usage here so the Literature Agent's token/cost footprint
        # lands in the manifest's llm_usage like every other sub-agent.
        if extra_llm_usage:
            ctx.llm_usage.extend(extra_llm_usage)
        ctx.memory_default_facts = self.memory_store.default_facts()
        mcp_manager = MCPClientManager(self._mcp_configs, ctx) if self._mcp_configs else None

        def fork_previous_run(parent_run_id: str, modification: str) -> str:
            child_run = self.run_store.create_run(f"Fork {parent_run_id}: {modification}")
            return self.execute_fork(child_run, parent_run_id, modification).run_id

        registry = _build_registry(
            ctx,
            run,
            self.run_store,
            self.critic_llm,
            self.model,
            mcp_manager,
            fork_previous_run_callback=fork_previous_run if session_context else None,
        )
        matched_skills = _select_skill_docs(user_request, skill_names)
        ctx.injected_skills = [skill.name for skill in matched_skills]
        system_prompt = build_augmented_system_prompt(SYSTEM_PROMPT, matched_skills)
        system_prompt = build_memory_augmented_system_prompt(system_prompt, self.memory_store)
        user_content = prompt_override or user_request
        if session_context:
            user_content = f"{session_context}\n\n当前用户请求：\n{user_content}"

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        emit({"type": "start"})
        summary = run_agent_loop(self.llm, messages, registry, run, ctx, emit, cancel_event)

        panel_path = run.run_dir / "panel.parquet"
        if ctx.cross_sectional and panel_path.exists():
            reproduce_data_path: str | None = str(panel_path)
        elif ctx.data_path:
            reproduce_data_path = str(ctx.data_path)
        else:
            reproduce_data_path = None
        factor_observations = len(ctx.panel_df) if ctx.panel_df is not None else None
        if factor_observations is None and ctx.data_df is not None:
            factor_observations = len(ctx.data_df)

        config = {
            "hypothesis": user_request,
            "model": self.model,
            "critic_model": self.critic_model,
            "data_path": reproduce_data_path,
            "cache": ctx.cache_meta,
            "data_slices": _data_slices_from_cache(ctx.cache_meta),
            "funding": ctx.funding_meta,
            "universe": ctx.universe.to_dict() if ctx.universe else None,
            "execution": (ctx.execution or ExecutionConfig()).to_dict(),
            "cost_model": ctx.cost_model,
            "borrow_model": ctx.borrow_model,
            "neutralize": ctx.neutralize,
            "capacity_curve": ctx.capacity_curve,
            "long_short_contribution": ctx.long_short_contribution,
            "neutralization_comparison": ctx.neutralization_comparison,
            # Only set for single-symbol runs (ctx.fetch_params is populated by
            # _fetch_ohlcv). Nothing else in config.yaml/backtest_result.json
            # records which symbol/timeframe a single-symbol run actually used -
            # quantbench/monitor/pipeline.py needs this to know what to
            # re-fetch when checking a run for decay later.
            "fetch_params": ctx.fetch_params,
            "parent_run_id": parent_run_id,
            "derived_from_factor": derived_from_factor,
            "injected_skills": ctx.injected_skills,
            "factor_metadata": _factor_metadata(ctx.signal_code or "", factor_observations),
            "session_id": session_id,
            "turn_index": turn_index,
            "applied_memory_defaults": ctx.applied_memory_defaults,
            "literature_source": literature_source,
        }
        run.save_config(config)

        metrics = ctx.last_metrics or {}
        if ctx.data_path:
            data_hash = f"sha256:{file_sha256(ctx.data_path)}"
        elif panel_path.exists():
            data_hash = f"sha256:{file_sha256(panel_path)}"
        else:
            data_hash = "sha256:none"
        code_path = run.run_dir / "signal.py"
        code_hash = f"sha256:{file_sha256(code_path)}" if code_path.exists() else "sha256:none"

        _run_critic_for_context(ctx, run, self.critic_llm, summary, _critic_context(ctx))

        if ctx.cross_sectional:
            note = build_cross_sectional_research_note(
                run.run_id,
                config,
                metrics,
                data_hash,
                ctx.warnings,
                summary,
                ctx.data_quality.to_dict() if ctx.data_quality else None,
                ctx.review_report.to_markdown() if ctx.review_report else "",
                ctx.critic_report.to_markdown() if ctx.critic_report else "",
                metrics_ci=_metrics_ci_for_run(run.run_dir),
                ic_significance=_ic_significance_for_run(run.run_dir),
            )
        else:
            note = build_research_note(
                run.run_id,
                config,
                metrics,
                data_hash,
                ctx.warnings,
                summary,
                ctx.review_report.to_markdown() if ctx.review_report else "",
                ctx.critic_report.to_markdown() if ctx.critic_report else "",
                metrics_ci=_metrics_ci_for_run(run.run_dir),
            )
        run.save_text("research_note.md", note)
        run.save_json("conversation.json", messages)
        run.finalize(
            data_hash=data_hash,
            code_hash=code_hash,
            warnings=ctx.warnings,
            model=self.model,
            critic_model=self.critic_model,
            conversation_log="conversation.json",
            summary=summary,
            metrics=metrics,
            review=ctx.review_report.to_dict() if ctx.review_report else None,
            critic=ctx.critic_report.to_dict() if ctx.critic_report else None,
            parent_run_id=parent_run_id,
            injected_skills=ctx.injected_skills,
            data_slices=_data_slices_from_cache(ctx.cache_meta),
            delegations=ctx.delegations,
            sandbox_usage=[asdict(item) for item in ctx.sandbox_usage],
            mcp_calls=ctx.mcp_calls,
            staging=ctx.staging,
            session_id=session_id,
            turn_index=turn_index,
            applied_memory_defaults=ctx.applied_memory_defaults,
            memory_events=ctx.memory_events,
            llm_usage=ctx.llm_usage,
            literature_source=literature_source,
        )
        if mcp_manager is not None:
            mcp_manager.close()

        return RunResult(
            run_id=run.run_id,
            run_dir=run.run_dir,
            metrics=metrics,
            warnings=ctx.warnings,
            summary=summary,
        )

    def _execute_library_question(
        self,
        run,
        user_request: str,
        emit: Callable[[dict[str, Any]], None],
        session_id: str | None = None,
        turn_index: int | None = None,
    ) -> RunResult:
        rows = summarize_library(ExperimentIndex.build())
        aggregate_json = json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)
        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You answer QuantBench experiment-library questions. Any number, ranking, or comparison in your "
                    "answer must come only from the injected aggregate table. Do not estimate or recount runs yourself. "
                    "If a group has sample_warning=true, state that the sample is too small for a firm conclusion."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User question: {user_request}\n\n"
                    "Deterministic aggregate table from quantbench.library.aggregate.summarize():\n"
                    f"{aggregate_json}"
                ),
            },
        ]
        emit({"type": "start", "mode": "library_question"})
        response = self.llm.chat(messages, tools=[])
        message = response.choices[0].message
        summary = message.content or ""
        emit({"type": "final", "summary": summary})

        config = {
            "hypothesis": user_request,
            "model": self.model,
            "critic_model": self.critic_model,
            "library_question": True,
            "session_id": session_id,
            "turn_index": turn_index,
            "applied_memory_defaults": [],
        }
        run.save_config(config)
        run.save_json("library_summary.json", rows)
        run.save_json("conversation.json", messages + [_message_to_dict(message)])
        note = build_research_note(
            run.run_id,
            config,
            {},
            "sha256:none",
            [],
            summary,
            "(实验库问答模式：未运行 Reviewer 审查)",
            "(实验库问答模式：未运行 Critic Agent 独立复核)",
        )
        run.save_text("research_note.md", note)
        run.finalize(
            data_hash="sha256:none",
            code_hash="sha256:none",
            warnings=[],
            model=self.model,
            critic_model=self.critic_model,
            conversation_log="conversation.json",
            summary=summary,
            metrics={},
            review=None,
            session_id=session_id,
            turn_index=turn_index,
            applied_memory_defaults=[],
            memory_events=[],
            llm_usage=[],
        )
        return RunResult(run_id=run.run_id, run_dir=run.run_dir, metrics={}, warnings=[], summary=summary)

    def execute_fork(
        self,
        run,
        parent_run_id: str,
        modification_request: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RunResult:
        seed_config = build_fork_config(parent_run_id, modification_request)

        # v1 fork only supports single-symbol parents. A cross-sectional parent's
        # data_path points at panel.parquet (a multi-symbol panel); feeding that
        # into the single-symbol vectorized backtest below would silently produce
        # garbage. Refuse explicitly rather than run the wrong math.
        if seed_config.get("universe"):
            raise ValueError(
                f"Fork not supported for cross-sectional run {parent_run_id}: "
                "forking multi-symbol (universe) experiments is not implemented yet. "
                "Fork a single-symbol run instead."
            )

        data_path = Path(seed_config["data_path"]) if seed_config.get("data_path") else None

        ctx = _RunContext()
        ctx.cache_meta = seed_config.get("cache")
        if data_path and data_path.exists():
            fixed_df = pd.read_parquet(data_path)
            ctx.data_path = data_path
            ctx.data_df = fixed_df
        else:
            ctx.warnings.append("Fork parent data_path is missing; backtest cannot run until fixed data is available.")

        registry = _build_fork_registry(ctx, run)

        def emit(event: dict[str, Any]) -> None:
            if on_event is not None:
                on_event(event)

        fork_prompt = (
            f"This is a fork of {parent_run_id}. The data and universe are fixed and already loaded. "
            "Only rewrite the compute() signal according to the user's modification. "
            "Do not fetch data or change the universe.\n\n"
            f"Modification request: {modification_request}\n\n"
            "Parent signal code:\n"
            f"{seed_config.get('parent_signal_code', '')}"
        )
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": fork_prompt},
        ]

        emit({"type": "start", "parent_run_id": parent_run_id})
        summary = run_agent_loop(self.llm, messages, registry, run, ctx, emit, cancel_event)

        metrics = ctx.last_metrics or {}
        config = {
            **{key: value for key, value in seed_config.items() if key != "parent_signal_code"},
            "hypothesis": f"{seed_config.get('hypothesis', '')} | fork: {modification_request}",
            "model": self.model,
            "critic_model": self.critic_model,
        }
        run.save_config(config)

        if data_path and data_path.exists():
            data_hash = f"sha256:{file_sha256(data_path)}"
        else:
            data_hash = seed_config.get("parent_data_hash") or "sha256:none"
        parent_hash = seed_config.get("parent_data_hash")
        if parent_hash and data_hash != parent_hash:
            ctx.warnings.append("Fork data drift: child data_hash differs from parent data_hash.")

        code_path = run.run_dir / "signal.py"
        code_hash = f"sha256:{file_sha256(code_path)}" if code_path.exists() else "sha256:none"
        _run_critic_for_context(ctx, run, self.critic_llm, summary, _critic_context(ctx))
        note = build_research_note(
            run.run_id,
            config,
            metrics,
            data_hash,
            ctx.warnings,
            summary,
            ctx.review_report.to_markdown() if ctx.review_report else "",
            ctx.critic_report.to_markdown() if ctx.critic_report else "",
            _fork_lineage_markdown(parent_run_id, seed_config.get("parent_signal_code", ""), code_path, metrics),
            metrics_ci=_metrics_ci_for_run(run.run_dir),
        )
        run.save_text("research_note.md", note)
        run.save_json("conversation.json", messages)
        run.finalize(
            data_hash=data_hash,
            code_hash=code_hash,
            warnings=ctx.warnings,
            model=self.model,
            critic_model=self.critic_model,
            conversation_log="conversation.json",
            summary=summary,
            metrics=metrics,
            review=ctx.review_report.to_dict() if ctx.review_report else None,
            critic=ctx.critic_report.to_dict() if ctx.critic_report else None,
            parent_run_id=parent_run_id,
            delegations=ctx.delegations,
            sandbox_usage=[asdict(item) for item in ctx.sandbox_usage],
            mcp_calls=ctx.mcp_calls,
            memory_events=[],
            llm_usage=ctx.llm_usage,
        )
        return RunResult(run_id=run.run_id, run_dir=run.run_dir, metrics=metrics, warnings=ctx.warnings, summary=summary)


def _select_skill_docs(user_request: str, skill_names: list[str] | None) -> list:
    registry = SkillRegistryDocs(DEFAULT_SKILL_DOCS_DIR)
    selected = []
    seen = set()
    for name in skill_names or []:
        doc = registry.get(name)
        selected.append(doc)
        seen.add(doc.name)
    for doc in registry.match(user_request):
        if doc.name not in seen:
            selected.append(doc)
            seen.add(doc.name)
    return selected


def _fetch_benchmark_returns(fetch_params: dict[str, str] | None, current_df) -> Any:
    if not fetch_params:
        return None
    symbol = fetch_params.get("symbol", "")
    benchmark = "BTC/USDT" if "/" in symbol else "SPY"
    try:
        if current_df is not None and symbol == benchmark:
            benchmark_df = current_df
        else:
            _, benchmark_df, _ = fetch_ohlcv(
                benchmark,
                fetch_params.get("timeframe", "1d"),
                fetch_params.get("start", ""),
                fetch_params.get("end", ""),
            )
        returns = benchmark_df["close"].pct_change()
        returns.index = pd.to_datetime(benchmark_df["timestamp"], utc=True)
        return returns
    except Exception:
        return None


def _is_library_question(user_request: str) -> bool:
    """Detect a cross-run experiment-library question (vs. a request to run a
    new backtest). Deliberately conservative: routing a real backtest request
    into library-question mode would silently skip the backtest, so we only
    match on phrases that clearly refer to the *existing* body of experiments,
    not on common single words like "run"/"best" that appear in ordinary
    backtest requests (e.g. "run a backtest to find the best momentum factor").
    """
    text = user_request.lower()
    history_markers = (
        "做过的所有",
        "所有实验",
        "实验库",
        "实验历史",
        "历史实验",
        "过往实验",
        "experiment library",
        "past experiments",
        "all experiments",
        "across runs",
        "my experiments",
        "my runs",
    )
    return any(marker in text for marker in history_markers)
