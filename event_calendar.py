"""
Scheduled high-impact events for crude oil and natural gas.

These two instruments are not driven by chart levels alone -- they are
driven, on a fixed weekly clock, by inventory data. A clean volume-backed
BUY fifteen minutes before the EIA crude number is not a good trade, it is
a coin flip with a spread on top, and the S/R model has no way to know the
number is coming. This module is that missing clock.

The recurring US energy calendar:
  - EIA Weekly Petroleum Status Report (crude stocks)  Wed 10:30 ET
  - EIA Weekly Natural Gas Storage Report              Thu 10:30 ET
  - API crude stocks (private, market-moving)          Tue 16:30 ET
  - Baker Hughes rig count                             Fri 13:00 ET

Times are US Eastern and converted to IST with real DST handling via
zoneinfo -- the ET->IST offset is 9h30 for most of the year but 10h30
during US daylight time, and hard-coding either one silently mistimes the
blackout for months at a stretch.

Holiday shifts: when a US federal holiday falls Monday-through-release-day
in a given week, EIA pushes that week's petroleum and gas releases back one
business day. The federal holiday dates are computed for whatever year is
being asked about -- via pandas' USFederalHolidayCalendar, which encodes the
observance rules (a Saturday holiday observed Friday, a Sunday one observed
Monday) rather than hard-coding a single year's dates -- so this keeps
working year after year with no edits. The returned event is flagged
`shifted=True` so the UI can say "delayed by a holiday this week" rather
than assert a time that has moved. This is an approximation of EIA's exact
rule, not a guarantee -- it exists to keep the blackout roughly honest
around holiday weeks, and the caller should still treat any near-release
window with care.
"""
from __future__ import annotations

import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import USFederalHolidayCalendar

ET = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")

_FED_CALENDAR = USFederalHolidayCalendar()


@lru_cache(maxsize=16)
def _federal_holidays(year: int) -> frozenset:
    """Observed US federal holiday dates for a calendar year, generated from
    the federal observance rules (cached per year -- the rules don't change
    within a year, and there are only a handful of years in play)."""
    hol = _FED_CALENDAR.holidays(start=f"{year}-01-01", end=f"{year}-12-31")
    return frozenset(ts.date() for ts in hol)

# weekday(): Mon=0 .. Sun=6
_WEEKLY = [
    {"id": "eia_crude", "name": "EIA Crude Inventories", "symbols": ("CRUDEOIL",),
     "weekday": 2, "hour": 10, "minute": 30, "impact": "high", "eia_shift": True},
    {"id": "eia_natgas", "name": "EIA Natural Gas Storage", "symbols": ("NATURALGAS",),
     "weekday": 3, "hour": 10, "minute": 30, "impact": "high", "eia_shift": True},
    {"id": "api_crude", "name": "API Crude Stocks", "symbols": ("CRUDEOIL",),
     "weekday": 1, "hour": 16, "minute": 30, "impact": "medium", "eia_shift": False},
    {"id": "rig_count", "name": "Baker Hughes Rig Count", "symbols": ("CRUDEOIL", "NATURALGAS"),
     "weekday": 4, "hour": 13, "minute": 0, "impact": "low", "eia_shift": False},
]

# Blackout window around a scheduled release, in minutes. Signals that fire
# inside it are suppressed/flagged rather than trusted: the pre window keeps
# the model from taking a position into the number, the post window lets the
# initial spike-and-whipsaw settle before a level means anything again.
BLACKOUT_PRE_MIN = 45
BLACKOUT_POST_MIN = 30


def _is_holiday(d: datetime.date) -> bool:
    return d in _federal_holidays(d.year)


def _apply_eia_shift(release_date: datetime.date) -> tuple[datetime.date, bool]:
    """Push an EIA release back one business day if a federal holiday fell
    Monday-through-release-day that week. Returns (date, shifted?)."""
    monday = release_date - datetime.timedelta(days=release_date.weekday())
    holiday_this_week = any(
        _is_holiday(monday + datetime.timedelta(days=i))
        for i in range((release_date - monday).days + 1)
    )
    if not holiday_this_week:
        return release_date, False
    shifted = release_date + datetime.timedelta(days=1)
    while shifted.weekday() >= 5 or _is_holiday(shifted):
        shifted += datetime.timedelta(days=1)
    return shifted, True


def _next_occurrence(ev: dict, now_et: datetime.datetime) -> tuple[datetime.datetime, bool]:
    """Next datetime (ET, tz-aware) this weekly event fires at or after now,
    plus whether an EIA holiday shift moved it."""
    days_ahead = (ev["weekday"] - now_et.weekday()) % 7
    candidate_date = (now_et + datetime.timedelta(days=days_ahead)).date()

    shifted = False
    if ev.get("eia_shift"):
        candidate_date, shifted = _apply_eia_shift(candidate_date)

    fire = datetime.datetime.combine(
        candidate_date, datetime.time(ev["hour"], ev["minute"]), tzinfo=ET)

    # If this week's instance has already passed, roll to next week's nominal
    # day and re-apply the shift (a shift can only move it later, so the
    # rolled date is still the correct next occurrence).
    if fire <= now_et:
        base_date = candidate_date + datetime.timedelta(days=7)
        # candidate_date may itself have been shifted; recompute from the
        # unshifted nominal day of next week to avoid compounding the shift.
        nominal_next = (now_et.date()
                        + datetime.timedelta(days=(ev["weekday"] - now_et.weekday()) % 7 + 7))
        base_date = nominal_next
        if ev.get("eia_shift"):
            base_date, shifted = _apply_eia_shift(base_date)
        else:
            shifted = False
        fire = datetime.datetime.combine(
            base_date, datetime.time(ev["hour"], ev["minute"]), tzinfo=ET)
    return fire, shifted


def upcoming_events(symbol: str, now: datetime.datetime | None = None, limit: int = 3) -> list[dict]:
    """The next few scheduled events for a symbol, soonest first.

    Each event: id, name, impact, when_ist (aware), minutes_until, shifted.
    now may be any tz-aware datetime; naive input is read as UTC.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    now_et = now.astimezone(ET)

    events = []
    for ev in _WEEKLY:
        if symbol not in ev["symbols"]:
            continue
        fire_et, shifted = _next_occurrence(ev, now_et)
        when_ist = fire_et.astimezone(IST)
        minutes_until = (fire_et - now_et).total_seconds() / 60.0
        events.append({
            "id": ev["id"], "name": ev["name"], "impact": ev["impact"],
            "when_ist": when_ist, "when_ist_str": when_ist.strftime("%a %d %b, %H:%M IST"),
            "minutes_until": round(minutes_until, 1), "shifted": shifted,
        })
    events.sort(key=lambda e: e["minutes_until"])
    return events[:limit]


def next_event(symbol: str, now: datetime.datetime | None = None) -> dict | None:
    """The single soonest scheduled event for a symbol, or None."""
    evs = upcoming_events(symbol, now, limit=1)
    return evs[0] if evs else None


def blackout(symbol: str, now: datetime.datetime | None = None,
             pre_min: int = BLACKOUT_PRE_MIN, post_min: int = BLACKOUT_POST_MIN) -> dict:
    """Whether `now` sits inside the pre/post window of a high- or
    medium-impact release for `symbol`.

    Returns {"active": bool, "event": <event or None>, "phase": "pre"|"post"|None}.
    Only high/medium-impact events open a blackout -- the Friday rig count
    moves price but not violently enough to void a level, so it is context,
    not a trading halt.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    for ev in upcoming_events(symbol, now, limit=5):
        if ev["impact"] not in ("high", "medium"):
            continue
        mins = ev["minutes_until"]
        if 0 <= mins <= pre_min:
            return {"active": True, "event": ev, "phase": "pre"}

    # Post window: check whether a release fired in the last `post_min`
    # minutes. upcoming_events only looks forward, so recompute the most
    # recent past occurrence directly.
    now_et = now.astimezone(ET)
    for ev in _WEEKLY:
        if symbol not in ev["symbols"] or ev["impact"] not in ("high", "medium"):
            continue
        fire_et, shifted = _next_occurrence(ev, now_et)
        last = fire_et - datetime.timedelta(days=7)
        if ev.get("eia_shift"):
            # re-derive the shift for the prior week
            shifted_date, _ = _apply_eia_shift(last.date())
            last = datetime.datetime.combine(shifted_date, last.timetz())
        mins_since = (now_et - last).total_seconds() / 60.0
        if 0 <= mins_since <= post_min:
            when_ist = last.astimezone(IST)
            return {"active": True, "phase": "post", "event": {
                "id": ev["id"], "name": ev["name"], "impact": ev["impact"],
                "when_ist": when_ist, "when_ist_str": when_ist.strftime("%a %d %b, %H:%M IST"),
                "minutes_until": round(-mins_since, 1), "shifted": shifted,
            }}
    return {"active": False, "event": None, "phase": None}


if __name__ == "__main__":
    now = datetime.datetime.now(datetime.timezone.utc)
    for sym in ("CRUDEOIL", "NATURALGAS"):
        print(f"\n{sym}:")
        for e in upcoming_events(sym, now):
            print(f"  {e['name']:28} {e['when_ist_str']}  in {e['minutes_until']/60:.1f}h"
                  f"{'  [holiday-shifted]' if e['shifted'] else ''}")
        b = blackout(sym, now)
        print(f"  blackout: {b['active']} phase={b['phase']}")
