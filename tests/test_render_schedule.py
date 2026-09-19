import datetime
import importlib.util
import os
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("render_schedule", os.path.join(ROOT, "tools", "render_schedule.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, h, mi=0):
    return datetime.datetime(y, m, d, h, mi, tzinfo=IST)


def test_weekday_window_boundaries():
    assert not rs.desired_running(ist(2026, 9, 21, 7, 59))        # Monday, just before open
    assert rs.desired_running(ist(2026, 9, 21, 8, 0))
    assert rs.desired_running(ist(2026, 9, 25, 16, 59))           # Friday, last minute
    assert not rs.desired_running(ist(2026, 9, 25, 17, 0))
    assert not rs.desired_running(ist(2026, 9, 22, 23, 30))


def test_weekend_is_always_off():
    for h in (0, 8, 12, 16, 23):
        assert not rs.desired_running(ist(2026, 9, 19, h))        # Saturday
        assert not rs.desired_running(ist(2026, 9, 20, h))        # Sunday


def test_utc_cron_times_map_to_the_ist_window():
    utc = datetime.timezone.utc
    assert rs.desired_running(datetime.datetime(2026, 9, 21, 2, 30, tzinfo=utc))       # 08:00 IST Monday
    assert not rs.desired_running(datetime.datetime(2026, 9, 21, 11, 30, tzinfo=utc))  # 17:00 IST Monday


def _svc(slug, suspended):
    return {"id": f"srv-{slug}", "slug": slug, "suspended": "suspended" if suspended else "not_suspended"}


def test_plan_resumes_suspended_services_inside_the_window():
    acts = rs.plan([_svc("finplus-1", True), _svc("alphapulse-sentiment-tracker", True)], ist(2026, 9, 21, 8, 5))
    assert sorted(a[0] for a in acts) == ["resume", "resume"]


def test_plan_suspends_running_services_outside_the_window():
    acts = rs.plan([_svc("finplus-1", False), _svc("alphapulse-sentiment-tracker", False)], ist(2026, 9, 20, 12, 0))
    assert sorted(a[0] for a in acts) == ["suspend", "suspend"]


def test_plan_does_nothing_when_already_correct_and_ignores_other_services():
    assert rs.plan([_svc("finplus-1", False), _svc("some-other-app", True)], ist(2026, 9, 21, 10, 0)) == []
    assert rs.plan([_svc("finplus-1", True), _svc("some-other-app", False)], ist(2026, 9, 21, 20, 0)) == []


def test_services_are_matched_by_slug_name_or_url():
    assert rs.match_slug({"slug": "finplus-1"}) == "finplus-1"
    assert rs.match_slug({"name": "FinPlus--1", "slug": "x"}) == "finplus-1"
    assert rs.match_slug({"slug": "zzz", "serviceDetails": {"url": "https://alphapulse-sentiment-tracker.onrender.com"}}) == "alphapulse-sentiment-tracker"
    assert rs.match_slug({"slug": "unrelated", "name": "other"}) is None
