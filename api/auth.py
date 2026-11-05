import hashlib
import hmac
import os
import time


COOKIE_NAME = "daybook_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


class AuthConfigurationError(Exception):
    pass


def settings():
    password = os.environ.get("APP_PASSWORD", "")
    secret = os.environ.get("APP_SESSION_SECRET", "")
    if not password and not secret and not os.environ.get("VERCEL"):
        return None
    if len(password) < 12:
        raise AuthConfigurationError("APP_PASSWORD must be at least 12 characters.")
    if len(secret) < 32:
        raise AuthConfigurationError("APP_SESSION_SECRET must be at least 32 characters.")
    return password.encode("utf-8"), secret.encode("utf-8")


def _signature(timestamp, secret):
    return hmac.new(secret, timestamp.encode("ascii"), hashlib.sha256).hexdigest()


def create_session(secret):
    timestamp = str(int(time.time()))
    return f"{timestamp}.{_signature(timestamp, secret)}"


def is_authenticated(cookie, secret):
    if not cookie:
        return False
    try:
        timestamp, signature = cookie.split(".", 1)
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > SESSION_SECONDS:
        return False
    expected = _signature(timestamp, secret)
    return hmac.compare_digest(signature, expected)


def verify_password(candidate, expected):
    return (
        isinstance(candidate, str)
        and hmac.compare_digest(candidate.encode("utf-8"), expected)
    )
