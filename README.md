# QuantBench

QuantBench is an AI workbench for quantitative research. It turns a plain-language strategy idea into a reproducible research run with data pulls, factor code, backtest metrics, charts, warnings, and an auditable artifact folder.

The goal is not to be an auto-trading bot. QuantBench is built for research: fast experiments, explicit assumptions, visible data-quality warnings, and results that can be reviewed before anyone trusts them.

![QuantBench drawdown artifact](docs/assets/drawdown.png)

## What It Does

- Converts natural-language research requests into executable quantitative experiments.
- Runs single-asset and cross-sectional backtests through a Python research engine.
- Builds universes such as S&P 500 samples and records important caveats like survivorship bias.
- Pulls market data through provider adapters such as `yfinance` and optional crypto exchange connectors.
- Produces artifacts for each run, including code, config, metrics, research notes, and charts.
- Serves a local Web workbench with session history, chat-style run output, artifact cards, and an inspector panel.
- Highlights warnings instead of hiding them, especially around synthetic data, survivorship bias, sample truncation, and data gaps.

## Project Shape

```text
quantbench/
  agent/        Coordinator and LLM-facing prompts
  api/          FastAPI endpoints for runs and artifacts
  artifact/     Run artifact storage
  data/         Data providers, universes, cache, and warehouse
  engine/       Vectorized and cross-sectional backtest logic
  skills/       Research skills: code execution, plots, reports, data quality
web/            React + Vite local workbench
tests/          Core, provider, API, CLI, and cross-sectional tests
```

Every research run is intended to leave a trail: the user request, generated code, config, metrics, warnings, plots, and a research note live together under `runs/<run_id>/`.

## Quick Start

Install Python dependencies:

```bash
uv sync
```

Run the CLI:

```bash
uv run python -m quantbench "用标普500里挑一小部分股票快速测一下动量因子的截面表现，2022到2024"
```

Start the API:

```bash
uv run uvicorn quantbench.api.server:app --reload
```

Start the Web workbench:

```bash
cd web
npm install
npm run dev
```

The Web UI expects the FastAPI server to be running locally.

## Current Status

QuantBench is an early research prototype with a working end-to-end loop:

- Phase 0: single-asset research runs, artifacts, plots, reports, and tests.
- Phase 1: cross-sectional research, S&P 500 universe support, data-quality reporting, and factor diagnostics.
- UI phase: local FastAPI API and React workbench for browsing runs and artifacts.

The screenshot artifact above comes from a small S&P 500 cross-sectional momentum test. That specific run intentionally shows strong warnings: the universe was truncated to 10 symbols and used current S&P 500 constituents across history, so it is not point-in-time and is not representative of the whole index.

## Roadmap

### Near Term

- Finish the local Web workbench polish: loading states, failed-run states, empty states, and artifact previews for more file types.
- Add streaming run progress with server-sent events or WebSocket updates.
- Improve run comparison so users can inspect multiple experiment variants side by side.
- Add stronger API and UI tests around artifact rendering and run status transitions.

### Research Quality

- Add a Reviewer Agent for look-ahead checks, overfitting diagnostics, cost sensitivity, out-of-sample decay, and regime dependence.
- Add point-in-time universe support to reduce survivorship bias in equity research.
- Add parameter stability sweeps and automatic stress tests.
- Expand data-quality checks for corporate actions, delistings, splits, missing sessions, and suspicious jumps.

### Data And Execution

- Add durable dataset versioning with clearer cache provenance.
- Support more providers for equities, crypto, futures, macro, and alternative data.
- Introduce optional sandboxed execution for user-defined research code.
- Add exportable experiment bundles for sharing and later reproduction.

### Product Direction

- Support experiment forking from any prior run.
- Build a searchable experiment library across hypotheses, metrics, warnings, and artifacts.
- Add richer native visualizations for equity curves, drawdowns, IC, group returns, and risk attribution.
- Add multi-session workflows for comparing strategies and research branches.

## Risk Statement

QuantBench outputs are research artifacts, not investment advice. Backtests can be wrong because of survivorship bias, look-ahead bias, data issues, unrealistic costs, overfitting, and market-regime dependence. Treat every result as something to review, reproduce, and stress-test before making decisions.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
