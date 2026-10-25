"""Short-lived 6-digit email codes + signed tokens (sign-up verification and password reset).

Codes live in Django's cache (use REDIS_URL in production so all workers share it), are stored
as keyed hashes, expire after 10 minutes and allow 5 wrong guesses.
"""
import secrets

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils.crypto import constant_time_compare, salted_hmac

CODE_TTL = 10 * 60
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = 30
TOKEN_MAX_AGE = 30 * 60


class TooSoon(Exception):
    pass


def _key(purpose, email):
    return f"kpcode:{purpose}:{email.strip().lower()}"


def _hash(purpose, email, code):
    return salted_hmac("kp-code", f"{purpose}:{email.strip().lower()}:{code}").hexdigest()


def issue_code(purpose, email):
    key = _key(purpose, email)
    if not cache.add(f"{key}:cooldown", 1, RESEND_COOLDOWN):
        raise TooSoon("Please wait a few seconds before requesting another code.")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    cache.set(key, {"h": _hash(purpose, email, code), "n": 0}, CODE_TTL)
    return code


def check_code(purpose, email, code):
    key = _key(purpose, email)
    data = cache.get(key)
    if not data:
        return False
    if data["n"] >= MAX_ATTEMPTS:
        cache.delete(key)
        return False
    if constant_time_compare(data["h"], _hash(purpose, email, str(code).strip())):
        cache.delete(key)
        return True
    data["n"] += 1
    cache.set(key, data, CODE_TTL)
    return False


def make_token(purpose, email, extra=""):
    return signing.dumps({"p": purpose, "e": email.strip().lower(), "x": extra}, salt=f"kp-{purpose}")


def read_token(purpose, token, max_age=TOKEN_MAX_AGE):
    """Return the token payload, or None if it is forged, expired or for another purpose."""
    try:
        data = signing.loads(token, salt=f"kp-{purpose}", max_age=max_age)
    except signing.BadSignature:
        return None
    return data if data.get("p") == purpose else None


def send_code_email(email, code, purpose):
    what = "verify your email" if purpose == "signup" else "reset your password"
    send_mail(
        subject="Your KP Global code",
        message=f"Use this code to {what}: {code}\n\nIt expires in 10 minutes. If you didn't ask for it, ignore this email.",
        from_email=None,
        recipient_list=[email],
    )
