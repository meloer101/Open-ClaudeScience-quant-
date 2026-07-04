"""Factor lifecycle state machine (GAP 5.2): research -> paper_tracking ->
live_candidate -> decayed -> retired. Pure functions only - FactorStore
(store.py) owns persistence and calls into this module to validate/apply
transitions.
"""

from __future__ import annotations

from quantbench.config import ALIVE_VERDICTS

RESEARCH = "research"
PAPER_TRACKING = "paper_tracking"
LIVE_CANDIDATE = "live_candidate"
DECAYED = "decayed"
RETIRED = "retired"

ALL_STATES = frozenset({RESEARCH, PAPER_TRACKING, LIVE_CANDIDATE, DECAYED, RETIRED})

# retired is reachable from every non-terminal state (explicit user action,
# never produced by next_state_from_decay), and once retired there is no
# transition back out - retiring a factor is a deliberate, final decision.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    RESEARCH: frozenset({PAPER_TRACKING, RETIRED}),
    PAPER_TRACKING: frozenset({LIVE_CANDIDATE, DECAYED, RETIRED}),
    LIVE_CANDIDATE: frozenset({DECAYED, RETIRED}),
    DECAYED: frozenset({RETIRED}),
    RETIRED: frozenset(),
}


def initial_state_for_verdict(verdict: str | None) -> str:
    """A factor saved from a run with verdict in ALIVE_VERDICTS starts life
    already on the daily paper-tracking loop; anything weaker is saved for
    reference only (e.g. a WEAK factor kept for comparison) and does not
    consume daily refresh/compute budget until someone explicitly promotes
    it - there is no such promotion path today, this just avoids silently
    paper-tracking factors nobody asked to track."""
    return PAPER_TRACKING if verdict in ALIVE_VERDICTS else RESEARCH


def next_state_from_decay(
    current_state: str,
    decay_status: str,
    *,
    days_tracked: int,
    consecutive_ok: int,
    promotion_min_days: int,
    promotion_min_consecutive_ok: int,
) -> str | None:
    """Returns the state to transition to, or None if no transition should
    happen. Never returns RETIRED - retirement is exclusively a user-initiated
    CLI action (`factor retire`), so a factor is never silently retired by an
    automated daily check."""
    if current_state not in {PAPER_TRACKING, LIVE_CANDIDATE}:
        return None

    if decay_status == "alert":
        return DECAYED if current_state != DECAYED else None

    if (
        current_state == PAPER_TRACKING
        and decay_status == "ok"
        and days_tracked >= promotion_min_days
        and consecutive_ok >= promotion_min_consecutive_ok
    ):
        return LIVE_CANDIDATE

    return None


def validate_transition(from_state: str, to_state: str) -> None:
    if to_state not in ALL_STATES:
        raise ValueError(f"unknown lifecycle state: {to_state!r}")
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
        raise ValueError(f"illegal lifecycle transition: {from_state!r} -> {to_state!r}")
