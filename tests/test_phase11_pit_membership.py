import pandas as pd

from quantbench.data.providers.sp500_history import (
    earliest_supported_date,
    membership_intervals,
    reconstruct_membership,
)


def _changes() -> pd.DataFrame:
    # Synthetic change log (no network). Chronological story:
    #   2019-06-01  AAA added,  OLD removed
    #   2020-03-15  BBB added,  AAA removed
    #   2021-09-10  CCC added,  BBB removed
    rows = [
        ("2019-06-01", "AAA", "OLD"),
        ("2020-03-15", "BBB", "AAA"),
        ("2021-09-10", "CCC", "BBB"),
    ]
    return pd.DataFrame(
        {
            "effective_date": pd.to_datetime([r[0] for r in rows], utc=True),
            "added": [r[1] for r in rows],
            "removed": [r[2] for r in rows],
        }
    )


def test_reconstruct_membership_reverses_future_changes():
    current = {"CCC", "STAY"}
    changes = _changes()

    # After every change: CCC in, BBB/AAA/OLD out.
    assert reconstruct_membership("2022-01-01", current, changes) == {"CCC", "STAY"}
    # Between the BBB->CCC and AAA->BBB swaps: BBB is the member, not CCC.
    assert reconstruct_membership("2021-01-01", current, changes) == {"BBB", "STAY"}
    # Before any of these changes: OLD was still in, AAA/BBB/CCC not yet.
    assert reconstruct_membership("2019-01-01", current, changes) == {"OLD", "STAY"}


def test_membership_intervals_clip_to_window_and_track_swaps():
    current = {"CCC", "STAY"}
    intervals = membership_intervals("2020-01-01", "2022-01-01", current, changes=_changes())

    # STAY is a member the whole window (single interval spanning it).
    assert intervals["STAY"] == [("2020-01-01", "2022-01-01")]
    # AAA was a member at window start, removed 2020-03-15.
    assert intervals["AAA"] == [("2020-01-01", "2020-03-15")]
    # BBB entered 2020-03-15, left 2021-09-10.
    assert intervals["BBB"] == [("2020-03-15", "2021-09-10")]
    # CCC entered 2021-09-10, still in at window end.
    assert intervals["CCC"] == [("2021-09-10", "2022-01-01")]
    # OLD left before the window entirely - never appears.
    assert "OLD" not in intervals


def test_earliest_supported_date_is_oldest_change():
    assert earliest_supported_date(_changes()) == pd.Timestamp("2019-06-01", tz="UTC")


def test_symbols_are_union_of_all_window_members():
    current = {"CCC", "STAY"}
    intervals = membership_intervals("2020-01-01", "2022-01-01", current, changes=_changes())
    assert set(intervals.keys()) == {"STAY", "AAA", "BBB", "CCC"}
