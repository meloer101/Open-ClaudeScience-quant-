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
