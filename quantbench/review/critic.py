from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from quantbench.review.report import ReviewReport

_VALID_VERDICTS = frozenset({"STRONG", "PROMISING", "WEAK", "REJECTED"})


@dataclass(frozen=True)
class CriticReport:
    status: str
    verdict: str | None
    agrees_with_deterministic_verdict: bool | None
    critique: str
    narrative_consistency_issues: list[str]
    recommended_next_steps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        if self.status != "ok":
            return f"Critic Agent 本次不可用：{self.critique}"

        issues = "\n".join(f"- {item}" for item in self.narrative_consistency_issues) or "- 未发现叙述一致性问题。"
        next_steps = "\n".join(f"- {item}" for item in self.recommended_next_steps) or "- 未提供额外建议。"
        if self.agrees_with_deterministic_verdict is None:
            agrees = "未知（Critic 未给出明确判断）"
        else:
            agrees = "是" if self.agrees_with_deterministic_verdict else "否"
        return (
            f"### 独立 verdict\n**{self.verdict or 'UNKNOWN'}**\n\n"
            f"### 是否认同确定性 verdict\n{agrees}\n\n"
            f"### Critique\n{self.critique}\n\n"
            f"### 叙述一致性问题\n{issues}\n\n"
            f"### 建议下一步\n{next_steps}"
        )


def run_critic(
    llm,
    *,
    code: str,
    review_report: ReviewReport,
    metrics: dict,
    summary: str,
    context: dict,
) -> CriticReport:
    try:
        user_payload = {
            "code": code,
            "metrics": metrics,
            "review_report": review_report.to_dict(),
            "coordinator_summary": summary,
            "context": context,
        }
        response = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an independent QuantBench Critic Agent. You did not write the signal code and "
                        "must not defend it. Use only the supplied deterministic evidence. Check whether the "
                        "Coordinator summary is numerically and narratively consistent with metrics and reviewer "
                        "findings, then give your independent verdict. Return only JSON with keys: verdict, "
                        "agrees_with_deterministic_verdict, critique, narrative_consistency_issues, "
                        "recommended_next_steps. The `verdict` field MUST be exactly one of these four strings: "
                        "STRONG, PROMISING, WEAK, REJECTED - no other values are valid."
                    ),
                },
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ],
            tools=[],
        )
        content = response.choices[0].message.content or ""
        payload = _parse_json(content)
        verdict = _optional_str(payload.get("verdict"))
        issues = _string_list(payload.get("narrative_consistency_issues"))
        if verdict is not None:
            verdict = verdict.upper()
            if verdict not in _VALID_VERDICTS:
                issues = [f"Critic returned an unrecognized verdict label '{verdict}'; discarded.", *issues]
                verdict = None
        return CriticReport(
            status="ok",
            verdict=verdict,
            agrees_with_deterministic_verdict=_optional_bool(payload.get("agrees_with_deterministic_verdict")),
            critique=str(payload.get("critique") or ""),
            narrative_consistency_issues=issues,
            recommended_next_steps=_string_list(payload.get("recommended_next_steps")),
        )
    except Exception as exc:
        return CriticReport(
            status="unavailable",
            verdict=None,
            agrees_with_deterministic_verdict=None,
            critique=f"{type(exc).__name__}: {exc}",
            narrative_consistency_issues=[],
            recommended_next_steps=[],
        )


def _parse_json(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("critic response must be a JSON object")
    return payload


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
