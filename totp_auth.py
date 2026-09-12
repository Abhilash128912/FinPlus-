"""
totp_auth.py - Automated INDmoney TOTP Authentication & Daily Token Refresher

Automates token generation so you never need to copy-paste tokens every day:
1. Generates the 6-digit TOTP dynamically via pyotp using your base32 TOTP secret.
2. Exchanges credentials + TOTP with INDmoney's authentication endpoint.
3. Automatically validates and saves the new JWT access token via token_manager.
4. Provides a scheduled morning auto-refresh (runs daily at 8:45 AM IST or when token < 60m).
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

# INDmoney / INDstocks Auth Endpoints
INDMONEY_API_BASE = "https://api.indstocks.com"
LOGIN_ENDPOINT = f"{INDMONEY_API_BASE}/user/login/verify-totp"
TOKEN_EXCHANGE_ENDPOINT = f"{INDMONEY_API_BASE}/user/token/generate"


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
    api_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """Attempts automated token generation using credentials and live TOTP.

    Returns (success, message_or_token).
    """
    cid = client_id or os.environ.get("INDMONEY_CLIENT_ID", "")
    pin = mpin or os.environ.get("INDMONEY_MPIN", "")
    secret = totp_secret or os.environ.get("INDMONEY_TOTP_SECRET", "")
    key = api_key or os.environ.get("INDMONEY_API_KEY", "")

    if not secret:
        return False, "INDMONEY_TOTP_SECRET is not configured in indmoney.env"

    current_otp = get_current_totp(secret)
    if not current_otp:
        return False, "Could not generate valid TOTP from secret"

    # Attempt auth call against INDmoney API
    payload = {
        "client_id": cid,
        "mpin": pin,
        "totp": current_otp,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["X-API-KEY"] = key

    try:
        # Try primary token generation endpoint
        resp = requests.post(TOKEN_EXCHANGE_ENDPOINT, json=payload, headers=headers, timeout=15)
        if resp.status_code == 404:
            # Fallback to secondary auth endpoint
            resp = requests.post(LOGIN_ENDPOINT, json=payload, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            # Find the token in common response shapes
            token = (
                data.get("data", {}).get("access_token")
                or data.get("access_token")
                or data.get("token")
                or data.get("data", {}).get("token")
            )
            if token:
                valid, reason = token_manager.test_token(token)
                if valid:
                    token_manager.save_token(token, BASE_DIR)
                    logger.info("Successfully refreshed INDmoney token via TOTP!")
                    return True, "Token successfully refreshed and applied."
                return False, f"Token obtained but failed live validation: {reason}"
            return False, f"Token not found in response: {resp.text[:200]}"
        else:
            return False, f"INDmoney auth returned HTTP {resp.status_code}: {resp.text[:200]}"
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
