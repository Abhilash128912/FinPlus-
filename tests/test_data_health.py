import datetime

import data_health as dh

IST = dh.IST


def _payload(**over):
    p = {
        "swing": {"picks": [{"symbol": "AAA", "ltp": 100.0, "swing_score": 70.0, "technicals_fresh": True, "technicals_as_of": "2026-09-18"}]},
        "lt": {"picks": [{"symbol": f"L{i}", "ltp": 50.0, "combined_rank_score": 80.0, "technicals_fresh": True, "technicals_as_of": "2026-09-18"} for i in range(6)]},
        "penny": {"picks": [{"symbol": "PPP", "ltp": 20.0, "total_score": 60.0, "technicals_fresh": True, "technicals_as_of": "2026-09-18"}]},
        "momentum": {"buy": [{"symbol": "BBB", "ltp": 10.0, "score": 80.0, "technicals_fresh": True}],
                     "sell": [{"symbol": "SSS", "ltp": 10.0, "score": 70.0, "technicals_fresh": True}]},
    }
    p.update(over)
    return p


NOW = datetime.datetime(2026, 9, 19, 10, 0, tzinfo=IST)      # Saturday -> last session Friday 18th


def _by(checks):
    return {c["name"]: c for c in checks}


def test_clean_payload_passes():
    c = _by(dh.evaluate_payload(_payload(), NOW))
    assert all(v["status"] == "OK" for v in c.values()), c


def test_empty_list_fails():
    c = _by(dh.evaluate_payload(_payload(swing=None), NOW))
    assert c["lists_populated"]["status"] == "FAIL"


def test_duplicates_and_bad_values_fail():
    p = _payload(penny={"picks": [{"symbol": "X", "ltp": 20.0, "total_score": 60.0}, {"symbol": "X", "ltp": -1.0, "total_score": 140.0}]})
    c = _by(dh.evaluate_payload(p, NOW))
    assert c["unique_symbols"]["status"] == "FAIL" and c["values_sane"]["status"] == "FAIL"


def test_snapshot_technicals_and_old_candles_warn():
    p = _payload(swing={"picks": [{"symbol": "AAA", "ltp": 100.0, "swing_score": 70.0, "technicals_fresh": False, "technicals_as_of": "2026-09-10"}]})
    c = _by(dh.evaluate_payload(p, NOW))
    assert c["fresh_technicals"]["status"] == "WARN" and c["candles_current"]["status"] == "WARN"


def test_last_session_date_rolls_back_over_weekend_and_premarket():
    assert dh.last_session_date(datetime.datetime(2026, 9, 20, 12, 0, tzinfo=IST)) == datetime.date(2026, 9, 18)   # Sunday
    assert dh.last_session_date(datetime.datetime(2026, 9, 21, 8, 0, tzinfo=IST)) == datetime.date(2026, 9, 18)    # Monday pre-open
    assert dh.last_session_date(datetime.datetime(2026, 9, 21, 10, 0, tzinfo=IST)) == datetime.date(2026, 9, 21)   # Monday in session


def test_price_cross_check_flags_a_mismatch(monkeypatch):
    class R:
        def json(self):
            return {"chart": {"result": [{"meta": {"regularMarketPrice": 90.0}}]}}
    monkeypatch.setattr(dh.requests, "get", lambda *a, **k: R())
    out = dh.price_cross_check(_payload(), sample=1)
    assert out["status"] == "WARN"


def test_price_cross_check_skips_when_source_unreachable(monkeypatch):
    def boom(*a, **k):
        raise dh.requests.ConnectionError("down")
    monkeypatch.setattr(dh.requests, "get", boom)
    assert dh.price_cross_check(_payload(), sample=2)["status"] == "SKIPPED"


def test_empty_lists_right_after_a_restart_warn_instead_of_fail():
    c = _by(dh.evaluate_payload(_payload(swing=None), NOW, uptime_sec=120))
    assert c["lists_populated"]["status"] == "WARN" and "warming up" in c["lists_populated"]["detail"]
    c = _by(dh.evaluate_payload(_payload(swing=None), NOW, uptime_sec=3 * 3600))
    assert c["lists_populated"]["status"] == "FAIL"
