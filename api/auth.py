"""Single-admin password and signed-session helpers."""

import base64
import hashlib
import hmac
import os
import time


COOKIE_NAME = "daybook_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


def configured():
    return bool(os.environ.get("ADMIN_PASSWORD")) and bool(os.environ.get("SESSION_SECRET"))


def password_matches(password):
    expected = os.environ.get("ADMIN_PASSWORD", "").encode("utf-8")
    if len(password) > 1024:
        return False
    supplied = password.encode("utf-8")
    return bool(expected) and hmac.compare_digest(supplied, expected)


def issue_token():
    expires = str(int(time.time()) + SESSION_MAX_AGE).encode("ascii")
    signature = hmac.new(
        os.environ["SESSION_SECRET"].encode("utf-8"),
        expires,
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(expires + b"." + signature).rstrip(b"=")
    return token.decode("ascii")


def valid_token(token):
    if not configured() or not token or len(token) > 128:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        expires, supplied_signature = decoded.split(b".", 1)
        if int(expires) < int(time.time()):
            return False
        expected_signature = hmac.new(
            os.environ["SESSION_SECRET"].encode("utf-8"),
            expires,
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(supplied_signature, expected_signature)
    except (ValueError, UnicodeEncodeError):
        return False
