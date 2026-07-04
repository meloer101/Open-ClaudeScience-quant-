# Changelog

## 0.1.0 - 2026-07-04

### First trusted-user release fixes

- Changed default execution fill from `close_t` to `open_t+1`.
- Explicit `close_t` runs now receive a Reviewer warning because same-close fills are optimistic.
- Fixed crypto perpetual funding cost estimation: funding history is paginated and intraday funding rows are aggregated into rebalance holding periods.
- Added local API token enforcement, localhost CORS allowlist defaults, and upload-based literature import to close the local-file ingest exposure.
- Conditioned crypto funding warnings on aligned coverage and failed-symbol metadata instead of warning unconditionally.

## 0.1.0-alpha - 2026-07-04

### Initial implementation

- Local AI workbench for reproducible quant research runs.
- Deterministic Reviewer with statistical, execution, data-quality, and cost findings.
- FastAPI + React local workspace for run browsing, artifacts, library, comparison, and paper workflows.
- Launch limitations: macOS/Linux first, research artifacts are not investment advice, and provider coverage limits remain documented in run warnings.
