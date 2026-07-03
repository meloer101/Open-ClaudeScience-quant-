from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quantbench.api import run_reader


FACTOR_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("momentum", ("momentum", "动量", "trend", "趋势")),
    ("reversal", ("reversal", "反转", "rsi", "mean reversion", "均值回归")),
    ("value", ("value", "价值", "估值")),
    ("volatility", ("volatility", "波动", "vol")),
    ("quality", ("quality", "质量", "盈利质量")),
    ("carry", ("carry", "利差", "期限")),
    ("liquidity", ("liquidity", "流动性", "volume", "成交量")),
)


@dataclass(frozen=True)
class ExperimentRecord:
    run_id: str
    hypothesis: str
    created_at: str
    status: str
    asset_class: str
    factor_family: str
    cross_sectional: bool
    sharpe: float | None
    annual_return: float | None
    max_drawdown: float | None
    turnover_annual: float | None
    ic_mean: float | None
    oos_sharpe: float | None
    verdict: str | None
    critic_verdict: str | None
    critic_agrees: bool | None
    critical_count: int
    warning_count: int
    parent_run_id: str | None
    error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_record(run_id: str) -> ExperimentRecord:
    manifest = run_reader.read_manifest(run_id) or {}
    config = run_reader.read_config(run_id) or {}
    status = run_reader.get_status(run_id)
    metrics = manifest.get("metrics") or {}
    review = manifest.get("review") or _read_review_report(run_id) or {}
    critic = manifest.get("critic") or _read_critic_report(run_id) or {}
    findings = review.get("findings") or []
    parent_run_id = manifest.get("parent_run_id") or config.get("parent_run_id")
    hypothesis = config.get("hypothesis") or manifest.get("user_request") or run_reader.read_user_request(run_id)

    return ExperimentRecord(
        run_id=run_id,
        hypothesis=hypothesis,
        created_at=manifest.get("created_at") or run_reader.created_at_from_run_id(run_id),
        status=status,
        asset_class=_classify_asset(config),
        factor_family=_classify_factor_family(config, hypothesis),
        cross_sectional=bool(config.get("universe")),
        sharpe=_number_or_none(metrics.get("sharpe")),
        annual_return=_number_or_none(metrics.get("annual_return")),
        max_drawdown=_number_or_none(metrics.get("max_drawdown")),
        turnover_annual=_number_or_none(metrics.get("turnover_annual")),
        ic_mean=_number_or_none(metrics.get("ic_mean")),
        oos_sharpe=_extract_oos_sharpe(findings),
        verdict=review.get("verdict"),
        critic_verdict=critic.get("verdict"),
        critic_agrees=critic.get("agrees_with_deterministic_verdict"),
        critical_count=sum(1 for finding in findings if str(finding.get("severity", "")).lower() == "critical"),
        warning_count=sum(1 for finding in findings if str(finding.get("severity", "")).lower() == "warning"),
        parent_run_id=parent_run_id,
        error_summary=_error_summary(run_id) if status == "failed" else None,
    )


def _read_review_report(run_id: str) -> dict[str, Any] | None:
    path = run_reader.run_dir_for(run_id) / "review_report.json"
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _read_critic_report(run_id: str) -> dict[str, Any] | None:
    path = run_reader.run_dir_for(run_id) / "critic_report.json"
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_oos_sharpe(findings: list[dict[str, Any]]) -> float | None:
    for finding in findings:
        if finding.get("check") != "out_of_sample":
            continue
        detail = finding.get("detail") or {}
        test_metrics = detail.get("test_metrics") or {}
        return _number_or_none(test_metrics.get("sharpe"))
    return None


def _classify_asset(config: dict[str, Any]) -> str:
    universe = config.get("universe") or {}
    explicit = universe.get("asset_class")
    if explicit:
        return str(explicit)

    provider = str(universe.get("provider") or universe.get("source") or "").lower()
    if "yfinance" in provider or "sp500" in provider:
        return "equity"
    if "ccxt" in provider or "binance" in provider:
        return "crypto"

    data_path = str(config.get("data_path") or "")
    data_name = Path(data_path).name.lower()
    if "ccxt" in data_name or "binance" in data_name or re.search(r"_[a-z]{2,6}_usdt[_\.]", data_name):
        return "crypto"
    if "yfinance_equity" in data_name:
        return "equity"

    symbols = universe.get("symbols") or []
    if symbols and all(re.fullmatch(r"[A-Z.]{1,6}", str(symbol)) for symbol in symbols[:20]):
        return "equity"
    return "unknown"


def _classify_factor_family(config: dict[str, Any], hypothesis: str) -> str:
    explicit = config.get("factor_family")
    if explicit:
        return str(explicit)
    text = hypothesis.lower()
    for family, keywords in FACTOR_FAMILY_KEYWORDS:
        if any(_keyword_matches(keyword.lower(), text) for keyword in keywords):
            return family
    return "unclassified"


def _keyword_matches(keyword: str, text: str) -> bool:
    """Match a keyword against text without ASCII-substring false positives.

    Plain `in` would let "vol" (volatility) match inside "volume" (liquidity),
    mislabelling a volume/liquidity factor as volatility and corrupting the
    aggregate table. We forbid an adjacent ASCII letter on either side, which
    keeps whole-word matching for English while still matching CJK keywords
    like "波动" (their neighbours are never ASCII letters).
    """
    return re.search(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", text) is not None


def _error_summary(run_id: str) -> str | None:
    error = run_reader.read_error(run_id)
    if not error:
        return None
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[-1] if lines else error.strip()


def signal_path(run_id: str) -> Path:
    return run_reader.run_dir_for(run_id) / "signal.py"
