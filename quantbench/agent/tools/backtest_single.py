from quantbench.agent.constants import RUN_SIGNAL_BACKTEST_PARAMS, SIGNAL_FILE_HARNESS, SIGNAL_FILE_HEADER
from quantbench.agent.helpers.benchmarks import _benchmark_symbol_from_fetch_params, _is_crypto_symbol
from quantbench.agent.helpers.config_normalizers import _execution_config
from quantbench.agent.helpers.research_notes_support import (
    _append_crypto_perpetual_warning,
    _backtest_payload_with_factor_metadata,
    _rerun_single_with_code,
    _review_warning_messages,
)
from quantbench.agent.run_context import _RunContext
from quantbench.config import DEFAULT_COST_BPS
from quantbench.engine.metrics import sanity_check_metrics
from quantbench.engine.vectorized_backtest import run_vectorized_backtest
from quantbench.review import run_review
from quantbench.agent.staging import CostEstimate, StagingGate
from quantbench.skills.codeexec import run_signal_code
from quantbench.skills.plot import save_drawdown_plot, save_equity_curve_plot
from quantbench.skills.registry import Skill


def build_run_signal_backtest_skill(ctx: _RunContext, run) -> Skill:
    def _run_signal_backtest(code: str, cost_bps: float = DEFAULT_COST_BPS, execution: dict[str, str] | None = None) -> dict:
        if ctx.screened:
            return {
                "error": "screen_factors already produced final, complete results for this session "
                "(backtest + Reviewer + Critic per candidate). Do not re-run individual backtests to "
                "re-verify or spot-check - report the screen_factors result directly in your final answer."
            }
        if ctx.data_df is None:
            return {"error": "no market data loaded yet - call fetch_ohlcv first"}

        signal = run_signal_code(code, ctx.data_df, usage_sink=ctx.sandbox_usage)
        staged = StagingGate(
            run_id=run.run_id,
            run_dir=run.run_dir,
            confirm_callback=ctx.staging_confirm,
        ).review(
            code=code,
            factor_values=signal,
            config={"cost_bps": cost_bps, "execution": execution},
            cost=CostEstimate(kind="single", observations=len(ctx.data_df)),
            hypothesis="single-asset signal",
            available_columns=list(ctx.data_df.columns),
        )
        ctx.staging = staged.artifact
        code = staged.code
        cost_bps = staged.config.get("cost_bps", cost_bps)
        execution = staged.config.get("execution", execution)
        if staged.code_changed:
            signal = run_signal_code(code, ctx.data_df, usage_sink=ctx.sandbox_usage)
        execution_config = _execution_config(execution)
        backtest = run_vectorized_backtest(ctx.data_df, signal, cost_bps=cost_bps, execution=execution_config)

        ctx.signal_code = code
        ctx.last_metrics = backtest.metrics
        ctx.cost_bps = cost_bps
        ctx.execution = execution_config
        run.save_code("signal.py", SIGNAL_FILE_HEADER + code + SIGNAL_FILE_HARNESS)
        run.save_json("backtest_result.json", _backtest_payload_with_factor_metadata(backtest, code, len(ctx.data_df)))
        save_equity_curve_plot(backtest.equity_curve, run.run_dir / "equity_curve.png")
        save_drawdown_plot(backtest.drawdown, run.run_dir / "drawdown.png")

        new_warnings = _append_crypto_perpetual_warning(ctx) if _is_crypto_symbol(ctx.fetch_params) else []
        new_warnings.extend(sanity_check_metrics(backtest.metrics))
        benchmark_symbol = _benchmark_symbol_from_fetch_params(ctx.fetch_params)

        # _fetch_benchmark_returns stays defined in coordinator.py (it calls
        # fetch_ohlcv, which tests/test_phase5_crypto_universe.py patches as a
        # module attribute on quantbench.agent.coordinator - importing the name
        # directly into this module would silently stop picking up that patch).
        # Deferred import: by the time this closure actually runs, coordinator.py
        # (the caller of build_run_signal_backtest_skill) is already fully
        # loaded, so this isn't a circular import.
        from quantbench.agent import coordinator as coordinator_module

        review_report = run_review(
            code=code,
            returns=backtest.returns,
            cost_bps=cost_bps,
            rerun_at_cost=lambda bps: run_vectorized_backtest(ctx.data_df, signal, cost_bps=bps, execution=execution_config).metrics,
            rerun_with_code=lambda candidate: _rerun_single_with_code(candidate, ctx.data_df, cost_bps),
            out_of_sample_data=ctx.data_df,
            run_on_data=lambda data: _rerun_single_with_code(code, data, cost_bps) or {},
            benchmark_returns=coordinator_module._fetch_benchmark_returns(ctx.fetch_params, ctx.data_df),
            benchmark_symbol=benchmark_symbol,
            turnover_annual=backtest.metrics.get("turnover_annual"),
            mcp_calls=ctx.mcp_calls,
        )
        ctx.review_report = review_report
        run.save_json("review_report.json", review_report.to_dict())
        review_warnings = _review_warning_messages(review_report)
        new_warnings.extend(review_warnings)
        ctx.warnings.extend(new_warnings)

        return {**backtest.metrics, "warnings": new_warnings, "review": review_report.to_dict()}

    return Skill(
        "run_signal_backtest",
        "Run signal code against the fetched data and backtest it.",
        RUN_SIGNAL_BACKTEST_PARAMS,
        _run_signal_backtest,
    )


def build_fork_run_signal_backtest_skill(ctx: _RunContext, run) -> Skill:
    def _run_signal_backtest(code: str, cost_bps: float = DEFAULT_COST_BPS, execution: dict[str, str] | None = None) -> dict:
        if ctx.data_df is None:
            return {"error": "fork data is unavailable - parent data_path could not be loaded"}

        signal = run_signal_code(code, ctx.data_df)
        execution_config = _execution_config(execution)
        backtest = run_vectorized_backtest(ctx.data_df, signal, cost_bps=cost_bps, execution=execution_config)

        ctx.signal_code = code
        ctx.last_metrics = backtest.metrics
        ctx.cost_bps = cost_bps
        ctx.execution = execution_config
        run.save_code("signal.py", SIGNAL_FILE_HEADER + code + SIGNAL_FILE_HARNESS)
        run.save_json("backtest_result.json", _backtest_payload_with_factor_metadata(backtest, code, len(ctx.data_df)))
        save_equity_curve_plot(backtest.equity_curve, run.run_dir / "equity_curve.png")
        save_drawdown_plot(backtest.drawdown, run.run_dir / "drawdown.png")

        new_warnings = sanity_check_metrics(backtest.metrics)
        review_report = run_review(
            code=code,
            returns=backtest.returns,
            cost_bps=cost_bps,
            rerun_at_cost=lambda bps: run_vectorized_backtest(ctx.data_df, signal, cost_bps=bps, execution=execution_config).metrics,
            rerun_with_code=lambda candidate: _rerun_single_with_code(candidate, ctx.data_df, cost_bps),
            out_of_sample_data=ctx.data_df,
            run_on_data=lambda data: _rerun_single_with_code(code, data, cost_bps) or {},
            benchmark_returns=None,
            turnover_annual=backtest.metrics.get("turnover_annual"),
            mcp_calls=ctx.mcp_calls,
        )
        ctx.review_report = review_report
        run.save_json("review_report.json", review_report.to_dict())
        new_warnings.extend(_review_warning_messages(review_report))
        ctx.warnings.extend(new_warnings)
        return {**backtest.metrics, "warnings": new_warnings, "review": review_report.to_dict()}

    return Skill(
        "run_signal_backtest",
        "Run revised fork signal code against the fixed parent data. No data fetching or universe changes are available.",
        RUN_SIGNAL_BACKTEST_PARAMS,
        _run_signal_backtest,
    )
