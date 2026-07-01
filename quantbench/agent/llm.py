import time

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
