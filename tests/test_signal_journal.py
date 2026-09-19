"""One independent trial must count once, however many times the refresh loop re-sees it."""
import datetime

import pandas as pd
import pytest

import signal_journal as sj


@pytest.fixture(autouse=True)
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(sj, "JOURNAL_FILE", str(tmp_path / "journal.json"))


def _sig(entry=269.7, stop=268.5, t1=272.0, setup="PDH_BREAK", rr=2.0, direction="BUY"):
    return {"srv_signal": direction, "srv_entry": entry, "srv_stop": stop, "srv_target1": t1,
            "srv_setup": setup, "srv_rr": rr}


def _t(h, m=0, day=18):
    return datetime.datetime(2026, 9, day, h, m, tzinfo=datetime.timezone.utc)


def test_resolved_signal_is_not_relogged_by_the_next_refresh():
    sj.log_signal("NATURALGAS", _sig(), _t(6))
    sj.evaluate("NATURALGAS", pd.DataFrame({"High": [269.9], "Low": [268.0]}, index=[pd.Timestamp("2026-09-18 06:05")]), _t(6, 5))
    assert sj._load()[0]["outcome"] == "stop"
    for minute in range(6, 40):                       # the refresh loop keeps seeing the same setup
        sj.log_signal("NATURALGAS", _sig(entry=269.7 + 0.01 * minute), _t(6, minute))
    assert len(sj._load()) == 1


def test_a_different_level_or_a_new_day_is_a_new_trial():
    sj.log_signal("NATURALGAS", _sig(), _t(6))
    sj.log_signal("NATURALGAS", _sig(entry=275.0, stop=273.8, t1=277.5), _t(7))     # far beyond one stop distance
    sj.log_signal("NATURALGAS", _sig(), _t(6, day=19))                              # next trading day
    assert len(sj._load()) == 3


def test_stats_collapse_historical_duplicates_without_touching_the_file():
    raw = [{"symbol": "NATURALGAS", "direction": "BUY", "setup": "PDH_BREAK", "entry": 269.7 + i * 0.01, "stop": 268.5,
            "target1": 272.0, "rr": 2.0, "opened_at": _t(6, i).isoformat(), "outcome": "stop",
            "closed_at": None, "bars_to_resolve": 1} for i in range(30)]
    sj._save(raw)
    s = sj.stats()
    assert s["raw_records"] == 30 and s["resolved"] == 1 and s["duplicates_collapsed"] == 29
    assert len(sj._load()) == 30                      # stored journal untouched


def test_same_bar_stop_and_target_is_counted_as_ambiguous():
    sj.log_signal("CRUDEOIL", _sig(entry=9800, stop=9750, t1=9900, setup="PDH_BREAK"), _t(6))
    sj.evaluate("CRUDEOIL", pd.DataFrame({"High": [9910.0], "Low": [9740.0]}, index=[pd.Timestamp("2026-09-18 06:05")]), _t(6, 5))
    s = sj.stats()
    assert s["losses"] == 1 and s["ambiguous_stops"] == 1


def test_win_without_recorded_rr_is_not_assumed_plus_one_r():
    sj._save([{"symbol": "X", "direction": "BUY", "setup": "s", "entry": 100.0, "stop": 99.0, "target1": 102.0, "rr": None,
               "opened_at": _t(6).isoformat(), "outcome": "target", "closed_at": None, "bars_to_resolve": 1}])
    assert sj.stats()["expectancy_r"] is None
