"""Synology login flow with 2FA support.

This module adds 2FA support to the existing SynologyClient.

Flow:
    1. Try a login with the saved device_token (if present)
    2. On success -> return SID
    3. If no token OR invalid token -> try a basic login
    4. If Synology returns code 403 (2FA required) -> ask for OTP
    5. Resend login with OTP + optional challenge token + enable_device_token=yes
    6. Save the returned device_id for future connections

Usage:
    from synmich.core.synology_auth import login_with_2fa

    sid = login_with_2fa(
        session=requests.Session(),
        base_url="https://192.168.0.2:5001",
        username="testtest",
        password="...",
        verify_ssl=False,
        otp_provider=cli_otp_prompt,  # function that returns the OTP
    )
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import requests

from synmich.core.device_tokens import (
    get_device_token,
    save_device_token,
    clear_device_token,
)

log = logging.getLogger("synmich")


class OTPRequired(Exception):
    """Raised when 2FA is required and no otp_provider is supplied."""

    def __init__(self, jwt_token: Optional[str], username: str):
        self.jwt_token = jwt_token
        self.username = username
        super().__init__(
            f"2FA OTP required for user '{username}'"
        )


class LoginFailed(Exception):
    """Raised if the Synology login fails for a non-recoverable reason."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"Synology login failed (code {code}): {message}")


# Synology Auth API error codes
_ERROR_MESSAGES = {
    400: "No such account or incorrect password",
    401: "Account disabled",
    402: "Permission denied (Synology Photos access required)",
    403: "2-step verification required",
    404: "Invalid 2-step verification code",
    405: "Authenticator app not installed",
    406: "2-factor authentication code required",
    407: "Source IP blocked by Synology",
    408: "Password expired (cannot be changed through this API)",
    409: "Password expired",
    410: "Password must be changed in DSM",
}


def _login_attempt(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool,
    *,
    otp_code: Optional[str] = None,
    jwt_token: Optional[str] = None,
    device_id: Optional[str] = None,
) -> dict:
    """Attempt a login. Return the raw JSON response from Synology."""

    # DSM documents OTP and trusted devices in v6. Only the richer challenge
    # flow needs v7; ordinary code-403 replies need neither JWT nor types.
    api_version = "7" if jwt_token else "6"

    data = {
        "api": "SYNO.API.Auth",
        "version": api_version,
        "method": "login",
        "account": username,
        "passwd": password,
        "format": "sid",
    }

    if otp_code:
        data["otp_code"] = otp_code
        data["enable_device_token"] = "yes"
        data["device_name"] = "synmich-cli"

    if jwt_token:
        data["token"] = jwt_token

    if device_id:
        data["device_id"] = device_id
        data["device_name"] = "synmich-cli"

    try:
        r = session.post(
            f"{base_url}/webapi/auth.cgi",
            data=data,
            verify=verify_ssl,
            timeout=30,
        )
        return r.json()
    except requests.RequestException as e:
        raise LoginFailed(0, f"Network error: {e}")


def login_with_2fa(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    verify_ssl: bool = False,
    otp_provider: Optional[Callable[[str], str]] = None,
) -> str:
    """Synology login with automatic 2FA handling.

    Args:
        session: requests.Session() to keep the cookies
        base_url: DSM URL (e.g. "https://192.168.0.2:5001")
        username: Synology username
        password: password
        verify_ssl: verify the SSL certificate
        otp_provider: function that takes `username` and returns the entered OTP.
            If None and 2FA is required -> raises OTPRequired.

    Returns:
        The Synology session SID.

    Raises:
        LoginFailed: if login fails for a non-recoverable reason.
        OTPRequired: if 2FA is required and no otp_provider is supplied.
    """

    # 1. Try with the saved device_token (if present)
    device_token = get_device_token(username, base_url)
    if device_token:
        log.info("Synology: trying login with saved device token for %s", username)
        r = _login_attempt(
            session, base_url, username, password, verify_ssl,
            device_id=device_token,
        )
        if r.get("success"):
            sid = r["data"]["sid"]
            log.info("Synology: login OK via device token (no OTP needed)")
            # The device_token is sometimes renewed
            new_did = r["data"].get("device_id") or r["data"].get("did")
            if new_did and new_did != device_token:
                save_device_token(username, base_url, new_did)
            return sid

        # Invalid token -> clear it and fall back to the standard flow
        log.info("Synology: device token rejected, falling back to OTP flow")
        clear_device_token(username, base_url)

    # 2. Basic login (no OTP, no token)
    r = _login_attempt(
        session, base_url, username, password, verify_ssl,
    )

    if r.get("success"):
        # No 2FA, direct login
        log.info("Synology: login OK (no 2FA on account)")
        return r["data"]["sid"]

    error = r.get("error", {})
    code = error.get("code", 0)

    # 3. If 2FA is required
    if code in (403, 406):
        errors = error.get("errors") or {}
        if not isinstance(errors, dict):
            errors = {}
        jwt_token = errors.get("token")
        types = errors.get("types") or []
        if types and not any(t.get("type") == "otp" for t in types if isinstance(t, dict)):
            raise LoginFailed(
                code,
                "This login challenge does not offer a verification code. "
                "Choose the 6-digit verification-code method in Synology Secure SignIn; "
                "push-only approval and security-key challenges are not supported.",
            )

        if otp_provider is None:
            raise OTPRequired(jwt_token, username)

        # Ask for the OTP (up to 3 attempts)
        for attempt in range(3):
            otp = otp_provider(username)
            if not otp:
                raise LoginFailed(code, "User cancelled OTP entry")

            r = _login_attempt(
                session, base_url, username, password, verify_ssl,
                otp_code=otp,
                jwt_token=jwt_token,
            )

            if r.get("success"):
                sid = r["data"]["sid"]
                # Save the device token for next time
                did = r["data"].get("device_id") or r["data"].get("did")
                if did:
                    save_device_token(username, base_url, did)
                log.info("Synology: login OK with OTP (device token saved)")
                return sid

            new_code = r.get("error", {}).get("code", 0)
            if new_code == 404:
                log.warning(
                    "Synology: invalid OTP code (attempt %d/3)", attempt + 1
                )
                continue
            else:
                raise LoginFailed(
                    new_code,
                    _ERROR_MESSAGES.get(new_code, "Unknown error"),
                )

        raise LoginFailed(404, "Maximum OTP attempts exceeded")

    # 4. Other error, non-recoverable
    raise LoginFailed(code, _ERROR_MESSAGES.get(code, "Unknown error"))


def fetch_user_id(
    session: requests.Session,
    base_url: str,
    sid: str,
    verify_ssl: bool = False,
) -> Optional[int]:
    """Return the Synology Photos user id for an authenticated session.

    Queries SYNO.Foto.UserInfo (method 'me'). The legacy login() did this
    right after auth; the v1.0.4 2FA rewrite dropped it, leaving
    SynologyClient.user_id=None. The Migrator maps album owners by syno
    user id (syno_id_to_session), so a missing id makes every owner lookup
    miss — albums get detected then marked done with 0 items uploaded.

    Returns None on any failure (network error, bad JSON, missing field);
    callers decide how to handle a missing id.
    """
    try:
        r = session.get(
            f"{base_url}/webapi/entry.cgi",
            params={
                "api": "SYNO.Foto.UserInfo",
                "method": "me",
                "version": "1",
                "_sid": sid,
            },
            verify=verify_ssl,
            timeout=30,
        )
        data = r.json().get("data", {}) or {}
    except (requests.RequestException, ValueError):
        return None
    uid = data.get("id")
    if uid is None:
        # Fallback: some DSM versions nest it under "user".
        uid = (data.get("user") or {}).get("id")
    return uid


def cli_otp_prompt(username: str) -> str:
    """Standard OTP prompt for the CLI.

    Uses click if available, otherwise falls back to input().
    """
    try:
        import click
        return click.prompt(
            f"  2FA code for {username} (6 digits)",
            type=str,
        ).strip()
    except ImportError:
        return input(f"  2FA code for {username} (6 digits): ").strip()
