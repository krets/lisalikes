import os
import time
import jwt
from fastapi import Header, HTTPException, Query

JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_SECRET = os.environ["ADMIN_SECRET"]
ALGO = "HS256"
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
REFRESH_THRESHOLD_SECONDS = 3 * 24 * 60 * 60  # refresh if <3 days left


def create_user_token() -> str:
    now = int(time.time())
    payload = {"role": "user", "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def maybe_refreshed_token(payload: dict) -> str | None:
    """Return a freshly-signed token if the current one is nearing expiry."""
    remaining = payload["exp"] - int(time.time())
    if remaining < REFRESH_THRESHOLD_SECONDS:
        return create_user_token()
    return None


def require_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    return decode_token(token)


def require_admin(secret: str = Query(default="")):
    # NOTE: passing secrets in a query string means they can end up in
    # server access logs, browser history, and Referer headers. Fine for a
    # small private tool behind your own VPS, but if you ever expose this
    # more broadly, switch this to a header (e.g. X-Admin-Secret) instead.
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    return True
