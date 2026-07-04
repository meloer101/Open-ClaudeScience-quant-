from __future__ import annotations


def estimate_request_cost(request: str) -> dict:
    text = request.strip()
    words = max(len(text.split()), 1)
    likely_cross_sectional = any(term in text.lower() for term in ("sp500", "s&p", "universe", "cross", "截面", "标普", "top"))
    coordinator_calls = 2 if likely_cross_sectional else 1
    critic_calls = 1
    estimated_tokens = max(1200, words * 12 + coordinator_calls * 1800 + critic_calls * 1200)
    estimated_usd = round(estimated_tokens / 1_000_000 * 2.0, 4)
    return {
        "estimated_tokens": estimated_tokens,
        "estimated_usd": estimated_usd,
        "coordinator_calls": coordinator_calls,
        "critic_calls": critic_calls,
        "note": "Deterministic preflight estimate; actual provider cost is recorded in manifest llm_usage after completion.",
    }
