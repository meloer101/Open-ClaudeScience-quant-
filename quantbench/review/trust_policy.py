from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustAssessment:
    tier: str
    severity: str
    message: str
    detail: dict[str, Any]


def assess_universe_trust(universe: dict[str, Any] | None) -> TrustAssessment:
    if not universe:
        return TrustAssessment(
            tier="single_asset_or_unspecified",
            severity="info",
            message="No cross-sectional universe trust tier applies to this run.",
            detail={},
        )

    asset_class = universe.get("asset_class")
    point_in_time = bool(universe.get("point_in_time"))
    covers_delisted = bool(universe.get("covers_delisted"))
    sample_limit = universe.get("sample_limit")
    source = universe.get("source")

    if asset_class == "crypto" and point_in_time:
        tier = "crypto_pit_snapshot_limited"
        severity = "warning"
        message = "Crypto point-in-time universe is snapshot-derived and launch-limited."
    elif point_in_time and covers_delisted:
        tier = "point_in_time_delisted_aware"
        severity = "pass"
        message = "Universe is point-in-time and provider metadata claims delisted coverage."
    elif point_in_time:
        tier = "point_in_time_membership_only"
        severity = "warning"
        message = "Universe membership is point-in-time, but delisted data coverage is not guaranteed."
    else:
        tier = "current_snapshot_survivorship_biased"
        severity = "warning"
        message = "Universe uses a current snapshot across history and remains survivorship-biased."

    if sample_limit:
        severity = "warning" if severity == "pass" else severity
        message += f" It is also limited to {sample_limit} symbols."

    return TrustAssessment(
        tier=tier,
        severity=severity,
        message=message,
        detail={
            "asset_class": asset_class,
            "point_in_time": point_in_time,
            "covers_delisted": covers_delisted,
            "sample_limit": sample_limit,
            "source": source,
        },
    )
