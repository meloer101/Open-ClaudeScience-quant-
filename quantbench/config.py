import os
from pathlib import Path


# Anchored to the package location rather than the current working directory,
# so data_cache/, runs/, and .env resolve consistently regardless of which
# directory the CLI happens to be invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE_DIR = PROJECT_ROOT / "data_cache"
RUNS_DIR = PROJECT_ROOT / "runs"
FACTORS_DIR = PROJECT_ROOT / "factors"
SKILL_DOCS_DIR = PROJECT_ROOT / "skills_docs"
DEFAULT_COST_BPS = 5.0
DEFAULT_MODEL = "deepseek/deepseek-chat"
MAX_STEPS = 12
SCREEN_MAX_CANDIDATES = 20
SCREEN_MAX_WORKERS = 4

# Risk parity (not max-sharpe) is the default: it never estimates expected
# returns, only covariance, which is the more reliably-estimated of the two
# inputs to portfolio optimization over a short factor-return history.
PORTFOLIO_DEFAULT_METHOD = "risk_parity"
PORTFOLIO_TRAIN_TEST_SPLIT = 0.7
PORTFOLIO_MAX_WEIGHT = 0.60
PORTFOLIO_MIN_FACTORS = 2
PORTFOLIO_MAX_FACTORS = 20
PORTFOLIO_MIN_OVERLAP_OBS = 60

# Live signal monitoring / decay alerts. Refresh windows overlap
# rather than fetch strictly-since-last-bar, because providers occasionally
# revise the most recent (possibly still-open) bar - upsert_ohlcv is
# idempotent on (symbol, timestamp) so re-fetching the overlap is free.
MONITOR_REFRESH_LOOKBACK_DAYS = 10
MONITOR_MIN_OBSERVATIONS = 5
# Same ratio thresholds as the out-of-sample review check (review/report.py)
# so "decayed since creation" and "decayed train->test" mean the same thing.
MONITOR_SHARPE_ALERT_RATIO = 0.5
MONITOR_SHARPE_WATCH_RATIO = 0.8
MONITOR_POLL_INTERVAL_SECONDS = 6 * 3600

# Signal-code execution sandbox (GAP 4.5 / PHASE13 1.1): conservative defaults for
# a research-scale single-asset backtest call, not a batch job. Callers that need
# more headroom pass an explicit SandboxConfig rather than raising these globally.
SANDBOX_CPU_SECONDS = 10
SANDBOX_MEM_MB = 1024
SANDBOX_WALL_TIMEOUT_S = 20.0
SANDBOX_MAX_WRITE_MB = 16


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()
CRITIC_MODEL = os.environ.get("QUANTBENCH_CRITIC_MODEL", DEFAULT_MODEL)
