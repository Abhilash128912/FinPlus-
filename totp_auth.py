"""
totp_auth.py - Automated INDmoney TOTP Authentication & Daily Token Refresher

Automates token generation so you never need to copy-paste tokens every day:
1. Generates the 6-digit TOTP dynamically via pyotp using your base32 TOTP secret.
2. Calls INDstocks' own documented TOTP token endpoint with mpin + totp.
3. Automatically validates and saves the new JWT access token via token_manager.
4. Provides a scheduled morning auto-refresh (runs daily at 8:45 AM IST or when token < 60m).

2026-09-19: this previously called guessed endpoints
(/user/login/verify-totp, /user/token/generate) that don't appear anywhere
in INDstocks' real API surface -- they silently 404'd, which is why this
was never actually configured. Confirmed against the real published docs
at api-docs.indstocks.com/Users/: the one true endpoint is POST
/generate/token, authenticated by an `x-api-key` header (the Client ID
INDstocks issues when you complete "Setup TOTP" on their access-tokens
page), with only {mpin, totp} in the body. This is an official INDstocks
feature built for exactly this purpose -- not reverse-engineered, not
scraped, and it requires its own one-time opt-in on their dashboard
(Setup TOTP -> scan QR -> confirm within 5 min -> Client ID is issued).
Docs also state: only one TOTP-generated token is live at a time (each
call invalidates the previous one), max 1 call per 60s, and 5 failed TOTP
attempts triggers a 15-minute lockout -- the refresher daemon below only
calls this a few times a day, well under either limit.
"""
import datetime
import logging
import os
import threading
import time
from typing import Optional, Tuple

import pyotp
import requests

import token_manager

logger = logging.getLogger("totp_auth")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# INDstocks' real, documented TOTP token endpoint (api-docs.indstocks.com/Users/).
INDMONEY_API_BASE = "https://api.indstocks.com"
TOKEN_GENERATE_ENDPOINT = f"{INDMONEY_API_BASE}/generate/token"


def get_current_totp(secret: Optional[str] = None) -> Optional[str]:
    """Generates the live 6-digit TOTP code using the stored or passed TOTP secret."""
    totp_secret = secret or os.environ.get("INDMONEY_TOTP_SECRET", "")
    totp_secret = totp_secret.replace(" ", "").strip()
    if not totp_secret:
        return None
    try:
        totp = pyotp.TOTP(totp_secret)
        return totp.now()
    except Exception as e:
        logger.error(f"Failed to generate TOTP: {e}")
        return None


def refresh_token_using_totp(
    client_id: Optional[str] = None,
    mpin: Optional[str] = None,
    totp_secret: Optional[str] = None,
) -> Tuple[bool, str]:
    """Calls INDstocks' real POST /generate/token with {mpin, totp}, the
    Client ID as the `x-api-key` header -- both issued together by their
    "Setup TOTP" flow on the access-tokens dashboard page, a one-time,
    INDstocks-sanctioned opt-in, not something scraped or reverse-engineered.

    Returns (success, message).
    """
    cid = client_id or os.environ.get("INDMONEY_CLIENT_ID", "")
    pin = mpin or os.environ.get("INDMONEY_MPIN", "")
    secret = totp_secret or os.environ.get("INDMONEY_TOTP_SECRET", "")

    if not cid:
        return False, "INDMONEY_CLIENT_ID is not configured in indmoney.env"
    if not pin:
        return False, "INDMONEY_MPIN is not configured in indmoney.env"
    if not secret:
        return False, "INDMONEY_TOTP_SECRET is not configured in indmoney.env"

    current_otp = get_current_totp(secret)
    if not current_otp:
        return False, "Could not generate valid TOTP from secret"

    payload = {"mpin": pin, "totp": current_otp}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": cid,
    }

    try:
        resp = requests.post(TOKEN_GENERATE_ENDPOINT, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # Docs (api-docs.indstocks.com/Users/) describe {"data": {"token": ...}},
            # but the live endpoint actually returns a flat {"token": ...} --
            # confirmed against a real successful call. Accept either shape.
            token = data.get("token") or (data.get("data") or {}).get("token")
            if token:
                valid, reason = token_manager.test_token(token)
                if valid:
                    token_manager.save_token(token, BASE_DIR)
                    logger.info("Successfully refreshed INDmoney token via TOTP!")
                    return True, "Token successfully refreshed and applied."
                return False, f"Token obtained but failed live validation: {reason}"
            return False, f"Token not found in response: {resp.text[:200]}"
        if resp.status_code == 429:
            return False, "Rate-limited by INDstocks (max 1 token/60s, or 15-min lockout after 5 failed TOTP attempts)."
        return False, f"INDstocks TOTP endpoint returned HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"TOTP auth request exception: {e}"


def _totp_refresher_daemon():
    """Background daemon that monitors token status.

    Fires:
    - At 8:45 AM IST every morning (before market open).
    - Whenever current token has < 45 minutes remaining and TOTP secret is present.
    """
    logger.info("TOTP auto-refresher daemon started.")
    while True:
        try:
            status = token_manager.get_token_status()
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            # IST is UTC + 5:30
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)

            is_morning_window = now_ist.hour == 8 and 40 <= now_ist.minute <= 50
            needs_refresh = (
                not status["has_token"]
                or status["is_expired"]
                or (status["expires_in_min"] is not None and status["expires_in_min"] < 45)
                or (is_morning_window and (status["expires_in_min"] or 0) < 300)
            )

            totp_secret = os.environ.get("INDMONEY_TOTP_SECRET")
            if needs_refresh and totp_secret:
                logger.info("Triggering scheduled TOTP token refresh...")
                ok, msg = refresh_token_using_totp()
                if ok:
                    logger.info("Automated TOTP refresh succeeded!")
                else:
                    logger.warning(f"Automated TOTP refresh attempt: {msg}")

        except Exception as e:
            logger.error(f"Error in TOTP refresher loop: {e}")

        # Sleep for 10 minutes between checks
        time.sleep(600)


def start_totp_refresher_thread():
    """Starts the automated daily TOTP background thread."""
    t = threading.Thread(target=_totp_refresher_daemon, daemon=True, name="totp_refresher")
    t.start()
    return t
