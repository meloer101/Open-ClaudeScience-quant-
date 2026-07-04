from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quantbench.agent.subagent import SubAgent, run_subagent
from quantbench.literature.paper import Paper
from quantbench.skills.registry import Skill, SkillRegistry

# The 4th SubAgent instance (after Critic and the memory-consolidation agent),
# exactly as PROJECT_STATUS anticipated. Its job is to READ a paper and DISTILL
# an actionable quant idea - not merely transcribe a formula. The output schema
# forces it to separate the economic hypothesis (why this is alpha) from the
# mechanical formula, and to record what the paper CLAIMS (reported_results) so
# the reproduction pipeline can build a "paper vs. our reproduction" table.

LITERATURE_AGENT_MAX_TURNS = 8

_SYSTEM_PROMPT = (
    "You are the QuantBench Literature Agent. You read a quantitative-finance paper and "
    "distill it into ONE actionable, testable factor. You are given the paper title, authors, "
    "and page 1 text up front; the rest of the paper is available on demand via the "
    "`read_paper_section` tool - call it to read the pages that define the factor, its formula, "
    "the universe/sample, and the reported results. Do not guess page contents you have not read.\n\n"
    "Your goal is to extract a QUANT IDEA a researcher could implement, not to transcribe math. "
    "Separate the economic hypothesis (why this should be alpha) from the mechanical formula. "
    "Be honest about what the paper leaves unspecified: mark implementation details you inferred "
    "versus those the paper states explicitly, and list them in `assumptions`.\n\n"
    "When you have enough, return ONLY a JSON object (no prose, no code fences) with keys: "
    "factor_name (short snake_case), economic_hypothesis, formula (natural language + math), "
    "compute_spec (how to implement it inside a Python `compute(df)` that returns a factor value "
    "per row; df has open/high/low/close/volume columns), suggested_universe "
    "(e.g. 'sp500' or 'crypto_perpetual'), suggested_timeframe, asset_class ('equity' or 'crypto'), "
    "direction ('long_high' or 'long_low'), reported_results (object with any of sharpe, annual_return, "
    "rank_ic, sample_period, universe the paper CLAIMS - use null for unknown), page_anchors "
    "(list of page numbers you relied on), assumptions (list of strings), known_caveats (list of strings). "
    "reported_results must reflect ONLY numbers the paper states; never invent them."
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "factor_name": {"type": "string"},
        "economic_hypothesis": {"type": "string"},
        "formula": {"type": "string"},
        "compute_spec": {"type": "string"},
        "suggested_universe": {"type": "string"},
        "suggested_timeframe": {"type": "string"},
        "asset_class": {"type": "string"},
        "direction": {"type": "string"},
        "reported_results": {"type": "object"},
        "page_anchors": {"type": "array", "items": {"type": "integer"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "known_caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["factor_name", "economic_hypothesis", "formula", "compute_spec"],
}


@dataclass(frozen=True)
class FactorExtraction:
    """Structured distillation of a paper into one factor. `reported_results`
    carries the paper's own claimed numbers, which the reproduction pipeline
    diffs against what we actually measure."""

    factor_name: str
    economic_hypothesis: str
    formula: str
    compute_spec: str
    suggested_universe: str | None = None
    suggested_timeframe: str | None = None
    asset_class: str | None = None
    direction: str | None = None
    reported_results: dict[str, Any] = field(default_factory=dict)
    page_anchors: list[int] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    known_caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FactorExtraction":
        def _str(key: str) -> str | None:
            value = payload.get(key)
            return str(value) if value not in (None, "") else None

        def _str_list(key: str) -> list[str]:
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if item not in (None, "")]
            return []

        def _int_list(key: str) -> list[int]:
            value = payload.get(key)
            out: list[int] = []
            if isinstance(value, list):
                for item in value:
                    try:
                        out.append(int(item))
                    except (TypeError, ValueError):
                        continue
            return out

        reported = payload.get("reported_results")
        return cls(
            factor_name=str(payload.get("factor_name") or "extracted_factor").strip(),
            economic_hypothesis=str(payload.get("economic_hypothesis") or ""),
            formula=str(payload.get("formula") or ""),
            compute_spec=str(payload.get("compute_spec") or ""),
            suggested_universe=_str("suggested_universe"),
            suggested_timeframe=_str("suggested_timeframe"),
            asset_class=_str("asset_class"),
            direction=_str("direction"),
            reported_results=reported if isinstance(reported, dict) else {},
            page_anchors=_int_list("page_anchors"),
            assumptions=_str_list("assumptions"),
            known_caveats=_str_list("known_caveats"),
        )


def _build_read_section_skill(paper: Paper) -> Skill:
    """Progressive-disclosure tool: the model reads pages on demand instead of
    the whole (possibly 30-page) paper being force-fed into context."""

    def _read_paper_section(start_page: int, end_page: int | None = None) -> dict[str, Any]:
        try:
            start = int(start_page)
        except (TypeError, ValueError):
            return {"error": "start_page must be an integer"}
        end = start if end_page is None else int(end_page)
        if start < 1 or end < start:
            return {"error": f"invalid page range {start}-{end}; pages are 1..{paper.n_pages}"}
        pages = paper.page_range_text(start, min(end, paper.n_pages))
        if not pages:
            return {"error": f"no pages in range {start}-{end}; paper has {paper.n_pages} pages"}
        return {
            "n_pages_total": paper.n_pages,
            "pages": [{"page_number": p.page_number, "text": p.text} for p in pages],
        }

    return Skill(
        name="read_paper_section",
        description=(
            "Read the extracted text of a page range from the paper being analyzed. "
            "Pages are 1-indexed. Use this to read the sections that define the factor, "
            "its formula, the sample/universe, and the reported results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "start_page": {"type": "integer", "description": "1-indexed first page"},
                "end_page": {"type": "integer", "description": "1-indexed last page (inclusive); defaults to start_page"},
            },
            "required": ["start_page"],
        },
        fn=_read_paper_section,
    )


def _initial_payload(paper: Paper, extra_instruction: str | None) -> dict[str, Any]:
    first_page = paper.pages[0].text if paper.pages else ""
    payload: dict[str, Any] = {
        "title": paper.title,
        "authors": paper.authors,
        "source": paper.source,
        "n_pages": paper.n_pages,
        "page_1_text": first_page[:6000],
    }
    if extra_instruction:
        payload["focus"] = extra_instruction
    return payload


def extract_factor(
    llm,
    paper: Paper,
    *,
    focus: str | None = None,
    usage_sink: list[dict[str, Any]] | None = None,
) -> FactorExtraction:
    """Run the Literature Agent over a paper and return a structured
    FactorExtraction. `focus` optionally narrows the extraction to a specific
    selection/section (used by the web 'ask about this selection' flow)."""
    registry = SkillRegistry()
    registry.register(_build_read_section_skill(paper))
    agent = SubAgent(
        name="literature",
        system_prompt=_SYSTEM_PROMPT,
        registry=registry,
        max_turns=LITERATURE_AGENT_MAX_TURNS,
        output_schema=_OUTPUT_SCHEMA,
    )
    payload = run_subagent(llm, agent, _initial_payload(paper, focus), usage_sink=usage_sink)
    return FactorExtraction.from_payload(payload)
