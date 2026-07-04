from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from quantbench.agent.subagent import SubAgent, run_subagent
from quantbench.api.session import Session
from quantbench.artifact.store import text_sha256
from quantbench.memory.store import UserMemoryStore
from quantbench.skills.registry import SkillRegistry


@dataclass(frozen=True)
class MemoryConsolidationResult:
    memory_events: list[dict[str, Any]]
    visible_messages: list[str]
    delegations: list[dict[str, Any]]
    llm_usage: list[dict[str, Any]]


def build_memory_consolidation_agent() -> SubAgent:
    return SubAgent(
        name="memory_consolidator",
        system_prompt=(
            "You extract durable user research preferences from a QuantBench session. "
            "Return JSON only: {\"candidates\": [{\"type\", \"description\", \"fields\", "
            "\"statement\", \"confidence\"}]}. Only propose stable defaults or preferences."
        ),
        registry=SkillRegistry(),
        max_turns=1,
        output_schema={"type": "object"},
    )


def consolidate_session(
    session: Session,
    *,
    memory_store: UserMemoryStore,
    llm,
    promotion_threshold: int = 2,
) -> MemoryConsolidationResult:
    agent = build_memory_consolidation_agent()
    payload = {
        "session_id": session.session_id,
        "turns": [
            {
                "turn_index": turn.turn_index,
                "user_message": turn.user_message,
                "run_id": turn.run_id,
                "summary": turn.summary,
            }
            for turn in session.turns
        ],
    }
    llm_usage: list[dict[str, Any]] = []
    output = run_subagent(llm, agent, payload, usage_sink=llm_usage)
    candidates = output.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    output_hash = f"sha256:{text_sha256(json.dumps(output, sort_keys=True, default=str))}"
    delegations = [{"name": agent.name, "turns_used": 1, "output_hash": output_hash}]
    emitted_events: list[dict[str, Any]] = []
    visible_messages: list[str] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        normalized = _normalize_candidate(candidate)
        if normalized is None:
            continue
        signature = _signature(normalized)
        candidate_event = memory_store.append_event(
            {
                "action": "candidate",
                "signature": signature,
                "candidate": normalized,
                "provenance": {"session_id": session.session_id, "run_ids": _run_ids(session), "source": "consolidation"},
            }
        )
        emitted_events.append(candidate_event)
        matching_sessions = _matching_candidate_sessions(memory_store.read_events(), signature)
        if len(matching_sessions) < promotion_threshold:
            continue

        action = "update" if _has_conflicting_fact(memory_store, normalized) else "write"
        fact = memory_store.write(
            {
                **normalized,
                "provenance": {
                    "sessions": matching_sessions,
                    "run_ids": _run_ids(session),
                    "source": "consolidation",
                },
            }
        )
        event = memory_store.append_event(
            {
                "action": action,
                "fact_id": fact.fact_id,
                "signature": signature,
                "provenance": {"session_id": session.session_id, "sessions": matching_sessions, "source": "consolidation"},
            }
        )
        emitted_events.append(event)
        visible_messages.append(f"已写入记忆: {fact.description}")

    return MemoryConsolidationResult(emitted_events, visible_messages, delegations, llm_usage)


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    fields = candidate.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return None
    return {
        "type": str(candidate.get("type") or "fact"),
        "description": str(candidate.get("description") or candidate.get("statement") or "User memory"),
        "fields": fields,
        "statement": str(candidate.get("statement") or candidate.get("description") or "User memory"),
        "confidence": float(candidate.get("confidence", 0.5)),
    }


def _signature(candidate: dict[str, Any]) -> str:
    return json.dumps(
        {
            "type": candidate.get("type"),
            "fields": candidate.get("fields") or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _matching_candidate_sessions(events: list[dict[str, Any]], signature: str) -> list[str]:
    sessions = {
        (event.get("provenance") or {}).get("session_id")
        for event in events
        if event.get("action") == "candidate" and event.get("signature") == signature
    }
    return sorted(session_id for session_id in sessions if session_id)


def _has_conflicting_fact(memory_store: UserMemoryStore, candidate: dict[str, Any]) -> bool:
    fields = set((candidate.get("fields") or {}).keys())
    for fact in memory_store.default_facts():
        if fact.type == candidate.get("type") and fields.intersection(fact.fields):
            return True
    return False


def _run_ids(session: Session) -> list[str]:
    return [turn.run_id for turn in session.turns if turn.run_id]
