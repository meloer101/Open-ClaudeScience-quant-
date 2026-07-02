---
name: reviewer-weak-triage
description: Workflow guidance for triaging a WEAK QuantBench reviewer verdict.
triggers:
  - weak verdict
  - Reviewer 给出 WEAK
  - reviewer weak
  - 打成 WEAK
  - verdict is weak
---
Start from the reviewer findings, not from the headline Sharpe.

If the warning is parameter sensitivity, test nearby parameter ranges and report whether the sign and rank ordering survive. If the warning is regime concentration, split results by year or market regime and identify whether one interval drives the result. If the warning is cost sensitivity, inspect turnover and rerun with higher costs before proposing refinements.

The next action should be either a targeted factor revision, a narrower scenario where the weakness is understood, or abandoning the idea. Do not present a WEAK result as production-ready.
