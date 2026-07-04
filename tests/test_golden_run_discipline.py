"""GAP 5.1 golden-run discipline: run the full golden-case registry and fail
loudly (with a readable summary table) if any case's verdict or required
finding severities drift from what they were pinned to. This is the
regression lock that catches a prompt change, a model swap, or a threshold
edit in quantbench/review/report.py silently shifting Reviewer behavior."""

from golden_run_registry import GOLDEN_CASES, REQUIRED_CATEGORIES, evaluate_case, render_summary


def test_golden_registry_covers_all_four_gap_categories():
    categories = {case.category for case in GOLDEN_CASES}
    assert categories == REQUIRED_CATEGORIES


def test_all_golden_cases_match_expected_verdict_and_findings():
    results = [evaluate_case(case) for case in GOLDEN_CASES]
    failed = [result for result in results if not result.verdict_ok or result.finding_mismatches]
    assert not failed, "\n\n" + render_summary(results)
