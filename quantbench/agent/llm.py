import time
from typing import Any

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5


class LLMClient:
    """Thin LiteLLM wrapper so Coordinator doesn't depend on litellm directly."""

    def __init__(self, model: str):
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        try:
            import litellm
        except ImportError as exc:
            raise RuntimeError("litellm is not installed. Run: pip install litellm") from exc

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return litellm.completion(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
            except Exception as exc:  # transient provider/network errors
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise last_error


def record_llm_usage(response: Any, model: str, usage_sink: list[dict[str, Any]] | None, *, step: str) -> None:
    """Extracts token usage + cost from an LLM response and appends it to
    usage_sink (GAP 5.4). Deliberately tolerant of responses with no `.usage`
    (e.g. FakeLLMClient in tests returns a bare SimpleNamespace) or of
    litellm.completion_cost failing for a model it doesn't have pricing for -
    either case just means no usage record is appended, never an exception
    reaching the caller. Cost uses litellm's own completion_cost() rather
    than a hand-rolled pricing table, since litellm already ships DeepSeek
    pricing and keeps it current."""
    if usage_sink is None:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    record: dict[str, Any] = {
        "step": step,
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    try:
        import litellm

        record["cost_usd"] = round(float(litellm.completion_cost(completion_response=response, model=model)), 6)
    except Exception:  # noqa: BLE001 - cost is a nice-to-have; usage counts still get recorded
        record["cost_usd"] = None
    usage_sink.append(record)
