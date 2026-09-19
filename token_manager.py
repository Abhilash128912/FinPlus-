"""
INDmoney access token: read, save, validate, and check expiry.

INDmoney has no programmable login flow (unlike Kite Connect's
request_token exchange) -- token generation is a manual action on their
own dashboard, so this can't be automated away. What this module removes
is the *file-editing* friction: save_token() writes the new value to
indmoney.env AND updates the live process's os.environ in the same call,
so a pasted token takes effect immediately, no restart needed -- the env
file only matters again on the *next* process start.

The token is a JWT; its payload carries `exp` (Unix seconds) openly (JWTs
are signed, not encrypted -- anyone holding the token can already read its
own claims, so base64-decoding it client-side to show "expires at HH:MM"
reveals nothing the token itself doesn't already expose).
"""
import base64
import json
import os
import time

import requests

ENV_FILE_NAME = "indmoney.env"
TOKEN_KEY = "INDMONEY_ACCESS_TOKEN"


def _env_file_path(base_dir: str) -> str:
    return os.path.join(base_dir, ENV_FILE_NAME)


def _load_finplus_key(base_dir: str) -> str:
    """Mirrors app.py's own _load_api_key() lookup. COMMAND's /api/token now
    requires this same header (2026-09-18: it used to accept anything, no
    key at all) -- reading it here rather than threading it through every
    save_token() caller (app.py's /settings route, totp_auth.py's daily
    auto-refresh) keeps this self-contained."""
    key = os.environ.get("FINPLUS_API_KEY", "").strip()
    if key:
        return key
    key = os.environ.get("SCREENER_SYNC_TOKEN", "").strip()
    if key:
        return key
    path = os.path.join(base_dir, "finplus_api_key.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("FINPLUS_API_KEY") and "=" in line:
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""


def _write_env_key(path: str, key: str, value: str) -> None:
    """Updates one KEY=value line in an .env file, preserving every other
    line untouched (MOBILE_BACKEND_URL and anything else a person or another
    tool -- e.g. FINPLUS COMMAND's shared-token broadcast -- put in this
    file). A previous version blindly overwrote the whole file with just
    this one line, silently deleting any other config on every token save."""
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{prefix}{value}\n"
            break
    else:
        lines.append(f"{prefix}{value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def decode_jwt_payload(token: str) -> dict | None:
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def get_token_status() -> dict:
    """Current in-process token's expiry, decoded from its own JWT payload
    -- not a guess, not a fixed 24h assumption, the exact claim INDmoney
    issued it with."""
    token = os.environ.get(TOKEN_KEY)
    if not token:
        return {"has_token": False, "expires_at": None, "is_expired": True, "expires_in_min": None}

    payload = decode_jwt_payload(token)
    if not payload or "exp" not in payload:
        return {"has_token": True, "expires_at": None, "is_expired": False, "expires_in_min": None}

    exp = payload["exp"]
    remaining_min = round((exp - time.time()) / 60, 1)
    return {
        "has_token": True,
        "expires_at": exp,
        "is_expired": remaining_min <= 0,
        "expires_in_min": remaining_min,
    }


def test_token(token: str) -> tuple[bool, str]:
    """Cheap live check: NIFTY 50 spot LTP is a single, near-instant call,
    and a bad/expired token fails it the same way any other call would --
    catching a pasted typo here beats discovering it mid-trading-day when
    every background loop starts erroring at once."""
    try:
        resp = requests.get("https://api.indstocks.com/market/quotes/ltp",
                             params={"scrip-codes": "NSE_40000001"},
                             headers={"Authorization": token.strip()}, timeout=15)
        if resp.status_code == 401:
            return False, "Rejected (401) -- token is invalid or expired"
        resp.raise_for_status()
        data = resp.json()
        if not data.get("data", {}).get("NSE_40000001", {}).get("live_price"):
            return False, f"Unexpected response: {resp.text[:200]}"
        return True, "OK"
    except requests.RequestException as e:
        return False, f"Request failed: {e}"


def save_token(new_token: str, base_dir: str, relay: bool = True) -> tuple[bool, str] | None:
    """Writes indmoney.env AND updates the running process's os.environ in
    the same call -- every background loop reads the token via
    os.environ.get() on each poll, not once at import time, so this takes
    effect on the very next tick, not the next restart. Also relays the
    token to the Render deployment if MOBILE_BACKEND_URL is configured;
    returns that relay's (ok, message), or None when no URL is set.

    save_token() rewrites only the token line and preserves every other key
    already in the file (INDMONEY_CLIENT_ID/MPIN/TOTP_SECRET, MOBILE_BACKEND_URL,
    ...) -- a TOTP auto-refresh must not destroy the credentials the *next*
    auto-refresh needs."""
    new_token = new_token.strip()
    _write_env_key(_env_file_path(base_dir), TOKEN_KEY, new_token)

    # Sync to FINPLUS COMMAND and notify master hub
    command_shared_paths = [
        r"D:\FINPLUS APPS\FINPLUS COMMAND\indmoney_shared.env",
        r"D:\FINPLUS WORKSPACE\indmoney_shared.env"
    ]
    for sp in command_shared_paths:
        try:
            with open(sp, "w", encoding="utf-8") as sf:
                sf.write(f"{TOKEN_KEY}={new_token}\n")
        except Exception:
            pass

    try:
        key = _load_finplus_key(base_dir)
        headers = {"X-Finplus-Key": key} if key else {}
        requests.post("http://localhost:9000/api/token", json={"token": new_token}, headers=headers, timeout=2)
    except Exception:
        pass

    os.environ[TOKEN_KEY] = new_token

    # relay=False when the token *came from* the backend (fetch_token_from_backend)
    # -- pushing it straight back would just be a pointless round trip.
    if not relay or not os.environ.get("MOBILE_BACKEND_URL", "").strip():
        return None
    return sync_token_to_mobile_backend(new_token)


def sync_token_to_mobile_backend(token: str) -> tuple[bool, str]:
    """Relays a freshly pasted token to the Render deployment so pasting it
    once on the laptop's own /settings page covers the phone too -- set
    MOBILE_BACKEND_URL (Render's service URL) once and this fires on every
    save_token() call; a blank/unset URL makes this a silent no-op rather
    than an error, since not everyone runs a second deployment. Uses
    FINPLUS_API_KEY as the X-Finplus-Key header, so the same secret must be
    configured on both the laptop and the Render service."""
    backend_url = os.environ.get("MOBILE_BACKEND_URL", "").strip().rstrip("/")
    if not backend_url:
        return False, "MOBILE_BACKEND_URL not set -- skipped"

    key = os.environ.get("FINPLUS_API_KEY", "").strip()
    try:
        resp = requests.post(
            f"{backend_url}/api/token",
            json={"token": token},
            headers={"X-Finplus-Key": key, "Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
        if resp.ok and data.get("success"):
            return True, "Synced to mobile backend"
        return False, f"Mobile backend rejected sync: {data.get('error') or resp.status_code}"
    except requests.RequestException as e:
        return False, f"Could not reach mobile backend: {e}"


def fetch_token_from_backend(base_dir: str) -> tuple[bool, str]:
    """Pulls the live INDmoney token from the Render deployment
    (GET {MOBILE_BACKEND_URL}/api/token/current, X-Finplus-Key auth).

    INDstocks keeps only one TOTP-generated token live at a time, so exactly
    one machine (Render) may run the TOTP auto-refresh; every other copy of
    this app calls this instead. Adopts the backend's token only if it
    outlives the local one, so a fresher local paste is never overwritten."""
    backend_url = os.environ.get("MOBILE_BACKEND_URL", "").strip().rstrip("/")
    if not backend_url:
        return False, "MOBILE_BACKEND_URL not set"
    key = _load_finplus_key(base_dir)
    if not key:
        return False, "No FinPlus key configured (FINPLUS_API_KEY / finplus_api_key.txt)"

    try:
        resp = requests.get(f"{backend_url}/api/token/current",
                            headers={"X-Finplus-Key": key}, timeout=15)
        if resp.status_code != 200:
            return False, f"Backend returned HTTP {resp.status_code}"
        token = (resp.json().get("token") or "").strip()
    except (requests.RequestException, ValueError) as e:
        return False, f"Could not fetch token from backend: {e}"
    if not token:
        return False, "Backend has no token"

    remote = decode_jwt_payload(token) or {}
    local = decode_jwt_payload(os.environ.get(TOKEN_KEY, "")) or {}
    if not remote.get("exp"):
        return False, "Backend token is not a readable JWT"
    if token == os.environ.get(TOKEN_KEY, "").strip() or remote["exp"] <= local.get("exp", 0):
        return True, "Local token already current"
    if remote["exp"] <= time.time():
        return False, "Backend token is itself expired"

    ok, detail = test_token(token)
    if not ok:
        return False, f"Backend token failed live check: {detail}"
    save_token(token, base_dir, relay=False)
    return True, "Token pulled from backend"


def _is_follower() -> bool:
    """True on a machine that should pull the token instead of generating it:
    a backend URL is configured, no local TOTP secret (so this copy never
    invalidates the backend's token), and we are not Render itself."""
    return (bool(os.environ.get("MOBILE_BACKEND_URL", "").strip())
            and not os.environ.get("INDMONEY_TOTP_SECRET", "").strip()
            and not os.environ.get("RENDER"))


def start_token_puller_thread(base_dir: str, interval_sec: int = 300):
    """Background poller for follower machines; a no-op everywhere else."""
    import threading

    def _loop():
        while True:
            try:
                if _is_follower():
                    ok, msg = fetch_token_from_backend(base_dir)
                    if not ok:
                        print(f"[token_puller] {msg}")
                    elif msg.startswith("Token pulled"):
                        print(f"[token_puller] {msg}")
            except Exception as e:
                print(f"[token_puller] error: {e}")
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, daemon=True, name="token_puller")
    t.start()
    return t
