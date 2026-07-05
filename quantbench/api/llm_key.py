from __future__ import annotations

import os
import re

from quantbench.config import DEFAULT_MODEL, MODEL_ENV, QUANTBENCH_HOME

ENV_FILE = QUANTBENCH_HOME / ".env"


def active_model() -> str:
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL)


def provider_key_env(model: str) -> str:
    """Derives the env var litellm reads a provider's API key from.

    litellm resolves a model's provider from the string before the first
    "/" (e.g. "openai/gpt-4o" -> openai, "moonshot/kimi-k2" -> moonshot) and
    looks up "<PROVIDER>_API_KEY" by convention - this matches that
    convention rather than inventing a QuantBench-specific one, so a key
    saved here is the same env var litellm itself expects.
    """
    provider = model.split("/", 1)[0] if "/" in model else model
    provider = re.sub(r"[^a-zA-Z0-9]+", "_", provider).strip("_").upper()
    if not provider:
        raise ValueError("model must include a non-empty provider name")
    return f"{provider}_API_KEY"


def llm_key_configured() -> bool:
    return bool(os.environ.get(provider_key_env(active_model()), "").strip())


def _set_env_var(name: str, value: str) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    replaced = False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                lines.append(f"{name}={value}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{name}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass

    # Takes effect immediately for this process (Coordinator reads MODEL_ENV
    # and the provider key fresh on every construction); config._load_dotenv()
    # picks both up on the next process start without resubmitting them.
    os.environ[name] = value


def store_llm_config(model: str, api_key: str) -> None:
    model = model.strip()
    api_key = api_key.strip()
    if not model:
        raise ValueError("model must not be empty")
    if not api_key:
        raise ValueError("api_key must not be empty")

    key_env = provider_key_env(model)
    _set_env_var(MODEL_ENV, model)
    _set_env_var(key_env, api_key)
