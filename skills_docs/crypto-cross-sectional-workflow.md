---
name: crypto-cross-sectional-workflow
description: Workflow guidance for crypto perpetual cross-sectional universe research.
triggers:
  - crypto 截面
  - 加密 截面
  - USDT 永续
  - USDT perpetual
  - top_usdt_perpetual
---
Use `build_universe` before `run_cross_sectional_backtest` for crypto cross-sectional requests.

For top-N-by-current-volume crypto universes, expect the effective historical panel to shrink when newer contracts lack older bars. Choose `n_groups` based on the number of symbols with usable data rather than assuming ten deciles are always valid.

Use BTC/USDT as the natural benchmark for crypto backtests. State clearly that perpetual funding-rate carry is not modeled, so long-short PnL across funding intervals can be biased.
