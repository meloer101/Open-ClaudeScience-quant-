import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _user_home() -> Path:
    return Path(os.environ.get("QUANTBENCH_HOME", Path.home() / ".quantbench")).expanduser()


# Runtime state must live outside the installed package/repository tree so a
# wheel install, read-only checkout, or app bundle can still create runs/cache.
QUANTBENCH_HOME = _user_home()
DATA_CACHE_DIR = QUANTBENCH_HOME / "data_cache"
RUNS_DIR = QUANTBENCH_HOME / "runs"
FACTORS_DIR = QUANTBENCH_HOME / "factors"
LITERATURE_DIR = QUANTBENCH_HOME / "literature"
SKILL_DOCS_DIR = PROJECT_ROOT / "skills_docs"
MCP_SERVERS_CONFIG = PROJECT_ROOT / "mcp_servers.json"
DEFAULT_COST_BPS = 5.0
DEFAULT_MODEL = "deepseek/deepseek-chat"
# Read fresh at Coordinator construction time (not cached into a module
# constant like CRITIC_MODEL below) so a model switched from the Web UI's
# setup modal takes effect on the very next run, no process restart required.
MODEL_ENV = "QUANTBENCH_MODEL"
MAX_STEPS = 12
SCREEN_MAX_CANDIDATES = 20
SCREEN_MAX_WORKERS = 4

# Execution backend for screen_factors fan-out: "local" (bounded ThreadPoolExecutor
# on this machine) or "remote" (SSH/Modal offload - interface reserved, not implemented).
# Switching to "remote" fails loudly rather than silently running locally.
EXECUTION_BACKEND = os.environ.get("QUANTBENCH_EXECUTION_BACKEND", "local")

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
# Verdicts worth continuing to watch after a run finishes - shared by decay
# monitoring (quantbench/monitor/pipeline.py) and the factor lifecycle's
# initial-state assignment (quantbench/factors/lifecycle.py), so "alive
# enough to keep checking" means the same thing in both places.
ALIVE_VERDICTS = {"STRONG", "PROMISING"}

# Alpha lifecycle / paper tracking (GAP 5.2): promotion from paper_tracking to
# live_candidate requires both enough elapsed days AND enough consecutive
# non-decayed checks - a single lucky day should not promote a factor, same
# "single occurrence doesn't count, repetition does" philosophy as the memory
# consolidation promotion gate (quantbench/memory/consolidation.py).
PAPER_TRACKING_PROMOTION_MIN_DAYS = 20
PAPER_TRACKING_PROMOTION_MIN_CONSECUTIVE_OK = 3

# Signal-code execution sandbox (GAP 4.5 / PHASE13 1.1): conservative defaults for
# a research-scale single-asset backtest call, not a batch job. Callers that need
# more headroom pass an explicit SandboxConfig rather than raising these globally.
SANDBOX_CPU_SECONDS = 10
SANDBOX_MEM_MB = 1024
SANDBOX_WALL_TIMEOUT_S = 20.0
SANDBOX_MAX_WRITE_MB = 16
SANDBOX_PANEL_CPU_SECONDS = 60
SANDBOX_PANEL_WALL_TIMEOUT_S = 120.0


def _load_dotenv() -> None:
    for env_path in (PROJECT_ROOT / ".env", QUANTBENCH_HOME / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()
CRITIC_MODEL = os.environ.get("QUANTBENCH_CRITIC_MODEL", DEFAULT_MODEL)
