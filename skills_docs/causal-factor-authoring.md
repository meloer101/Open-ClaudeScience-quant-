---
name: causal-factor-authoring
description: Rules for authoring causal compute(df) factor code without lookahead.
triggers:
  - future function
  - lookahead
  - shift(-1)
  - causal factor
  - 未来函数
  - 因果
---
Write `compute(df)` so each row uses only current and previous rows. Do not use `shift(-1)`, future returns, centered windows, or full-sample normalization that lets future observations influence past scores.

Return a raw factor or signal series, not a pre-thresholded backtest position unless the user explicitly asks for a rule-based trading signal. Handle warmup NaNs intentionally with `fillna(0)`, `ffill`, or leaving them missing when the engine can tolerate it.

For rolling windows and percentage changes, document the intended horizon through clear variable names so later factor-library parameter overrides are unambiguous.
