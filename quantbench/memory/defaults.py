from __future__ import annotations

from typing import Any

from quantbench.config import DEFAULT_COST_BPS
from quantbench.memory.store import UserMemoryFact


def apply_memory_defaults(config: dict[str, Any], facts: list[UserMemoryFact]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    final_config = dict(config)
    applied: list[dict[str, Any]] = []
    for fact in facts:
        for field, value in fact.fields.items():
            if not _can_apply_default(field, final_config):
                continue
            if final_config.get(field) == value:
                continue
            final_config[field] = value
            applied.append({"fact_id": fact.fact_id, "field": field, "value": value})
    return final_config, applied


def merge_applied_memory_defaults(existing: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {(item.get("fact_id"), item.get("field")) for item in merged}
    for item in new_items:
        key = (item.get("fact_id"), item.get("field"))
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def _can_apply_default(field: str, config: dict[str, Any]) -> bool:
    if field == "cost_bps":
        return config.get(field) in (None, DEFAULT_COST_BPS)
    return field in config and config.get(field) is None
