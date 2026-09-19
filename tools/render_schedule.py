"""
render_schedule.py -- keep the Render free-tier instance hours under the 750/month workspace cap by
running the FINPLUS services only during market hours.

Policy (IST): the services run Monday-Friday 08:00-17:00 and are SUSPENDED at all other times
(nights and the whole weekend). A suspended service uses no instance hours. Render has no built-in
schedule, so this script -- run every 30 minutes by a GitHub Actions cron -- reconciles the actual
state with the desired state by calling Render's API (suspend / resume). Running it more often than
needed is harmless: it only acts when the state differs, so a delayed or missed cron run heals itself.

Hours: 9 h x ~21.7 weekdays = ~195 h per service, ~390 h for both (cap 750 shared).

Usage:  RENDER_API_KEY=... python tools/render_schedule.py [--dry-run]
"""
from __future__ import annotations

import datetime
import os
import sys
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
API = "https://api.render.com/v1"

# Services to schedule. Each is matched by slug (the <slug>.onrender.com subdomain), display name or web
# address, whichever Render reports, so a renamed or blueprint-created service is still found.
SERVICE_SLUGS = ("finplus-1", "finplus", "alphapulse-sentiment-tracker")
_ALIASES = {
    "finplus-1": ("finplus-1", "finplus--1", "indmoney-trading-screener"),      # RADAR
    "finplus": ("finplus", "finplus-"),                                          # LEDGER backend
    "alphapulse-sentiment-tracker": ("alphapulse-sentiment-tracker", "alphapulse"),   # Pulse
}
# The services may live in different Render accounts/workspaces; one API key per account
# (GitHub secrets RENDER_API_KEY and RENDER_API_KEY_2). Free hours are per workspace.
KEY_ENV_VARS = ("RENDER_API_KEY", "RENDER_API_KEY_2")


def match_slug(service: dict) -> str | None:
    """Which of SERVICE_SLUGS this Render service is, or None."""
    host = ((service.get("serviceDetails") or {}).get("url") or "").lower().replace("https://", "").split(".")[0]
    candidates = {str(service.get("slug") or "").lower(), str(service.get("name") or "").lower(), host}
    for slug, names in _ALIASES.items():
        if candidates & set(names):
            return slug
    return None

# Weekdays 0=Mon..4=Fri. Window is [OPEN, CLOSE) in IST.
RUN_DAYS = (0, 1, 2, 3, 4)
OPEN = datetime.time(8, 0)
CLOSE = datetime.time(17, 0)


def desired_running(now: datetime.datetime | None = None) -> bool:
    now = (now or datetime.datetime.now(IST)).astimezone(IST)
    return now.weekday() in RUN_DAYS and OPEN <= now.time() < CLOSE


def plan(services: list[dict], now: datetime.datetime | None = None) -> list[tuple[str, str, str]]:
    """[(action, service_id, slug)] needed to reach the desired state. `services` are the `service`
    objects from Render's list-services response."""
    want_up = desired_running(now)
    actions = []
    for s in services:
        slug = match_slug(s)
        if slug is None:
            continue
        suspended = s.get("suspended") == "suspended"
        if want_up and suspended:
            actions.append(("resume", s["id"], slug))
        elif not want_up and not suspended:
            actions.append(("suspend", s["id"], slug))
    return actions


def annotate(level: str, message: str) -> None:
    """Also surface a result as a GitHub Actions annotation (readable without opening the raw log).
    Carries service names/slugs/states/HTTP codes only -- never the API key."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title=Render schedule::{message.replace(chr(10), ' | ')}")


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def list_services(key: str) -> list[dict]:
    out, cursor = [], None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{API}/services", headers=_headers(key), params=params, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return out
        out += [row["service"] for row in rows]
        cursor = rows[-1].get("cursor")
        if len(rows) < 100 or not cursor:
            return out


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    keys = [os.environ[v].strip() for v in KEY_ENV_VARS if os.environ.get(v, "").strip()]
    if not keys:
        print("RENDER_API_KEY is not set (add it as a GitHub Actions secret).")
        return 2
    now = datetime.datetime.now(IST)
    print(f"{now:%a %Y-%m-%d %H:%M} IST -> desired: {'RUNNING' if desired_running(now) else 'SUSPENDED'}")
    seen: list[dict] = []
    rc = 0
    for n, key in enumerate(keys, 1):
        services = list_services(key)
        seen += services
        actions = plan(services, now)
        managed = ", ".join(sorted(f"{match_slug(s)}={s.get('suspended')}" for s in services if match_slug(s))) or "none"
        print(f"key {n}: sees {len(services)} service(s); managed here: {managed}")
        if not actions:
            annotate("notice", f"key {n}: already in desired state "
                     f"({'RUNNING' if desired_running(now) else 'SUSPENDED'}); managed: {managed}")
        for action, sid, slug in actions:
            print(f"{'[dry-run] ' if dry else ''}{action} {slug} ({sid})")
            if dry:
                continue
            r = requests.post(f"{API}/services/{sid}/{action}", headers=_headers(key), timeout=30)
            print(f"  -> HTTP {r.status_code}")
            if r.status_code >= 300:
                print(r.text[:300])
                annotate("error", f"{action} {slug} failed: HTTP {r.status_code} {r.text[:200]}")
                rc = 1
            else:
                annotate("notice", f"{action} {slug}: HTTP {r.status_code}")
    found = {match_slug(s) for s in seen}
    missing = [slug for slug in SERVICE_SLUGS if slug not in found]
    if missing:
        listing = "; ".join(f"{s.get('name')} [{s.get('slug')}, {s.get('suspended')}]" for s in seen)
        print("WARNING: service(s) not found with the API key(s) provided:", ", ".join(missing))
        print("Services visible:", listing)
        annotate("error", "Not found: " + ", ".join(missing) + ". Visible: " + listing)
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
