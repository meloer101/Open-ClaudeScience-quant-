from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml


class ChatClient(Protocol):
    def complete(self, messages: list[dict]) -> str:
        ...


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    required_findings: list[str]
    output: str


def run_llm_cases(path: Path, client: ChatClient) -> list[EvalResult]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    results: list[EvalResult] = []
    for case in payload.get("cases", []):
        messages = [{"role": "user", "content": case["prompt"]}]
        output = client.complete(messages)
        required = [str(item) for item in case.get("required_findings", [])]
        passed = all(item.lower() in output.lower() for item in required)
        results.append(EvalResult(case["name"], passed, required, output))
    return results
