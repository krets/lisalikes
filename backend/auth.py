import os
import secrets
import time
import jwt
from fastapi import Cookie, Header, HTTPException, Query

from db import get_conn

JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_SECRET = os.environ["ADMIN_SECRET"]
ALGO = "HS256"
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
REFRESH_THRESHOLD_SECONDS = 3 * 24 * 60 * 60  # refresh if <3 days left
ADMIN_SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours, no refresh


def create_user_token(email: str | None = None) -> str:
    now = int(time.time())
    jti = secrets.token_urlsafe(16)
    exp = now + TOKEN_TTL_SECONDS
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO invites (jti, email, created_at, expires_at, last_seen_at, revoked_at) "
            "VALUES (?, ?, ?, ?, NULL, NULL)",
            (jti, email, now, exp),
        )
        conn.commit()
    payload = {"role": "user", "jti": jti, "iat": now, "exp": exp}
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
        now = int(time.time())
        exp = now + TOKEN_TTL_SECONDS
        with get_conn() as conn:
            conn.execute("UPDATE invites SET expires_at = ? WHERE jti = ?", (exp, payload["jti"]))
            conn.commit()
        return jwt.encode({"role": "user", "jti": payload["jti"], "iat": now, "exp": exp}, JWT_SECRET, algorithm=ALGO)
    return None


def require_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)

    now = int(time.time())
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM invites WHERE jti = ?", (payload.get("jti"),)).fetchone()
        if row is None or row["revoked_at"] is not None or row["expires_at"] < now:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        conn.execute("UPDATE invites SET last_seen_at = ? WHERE jti = ?", (now, payload["jti"]))
        conn.commit()

    return payload


def create_admin_session() -> str:
    now = int(time.time())
    payload = {"role": "admin", "iat": now, "exp": now + ADMIN_SESSION_TTL_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGO)


def require_admin(secret: str = Query(default=""), admin_session: str | None = Cookie(default=None)):
    # NOTE: ?secret= means the value can end up in server access logs, browser
    # history, and Referer headers. Kept only for scripts/invite.sh; the admin
    # web panel uses the admin_session cookie below instead.
    if secret and secret == ADMIN_SECRET:
        return True

    if admin_session:
        try:
            payload = jwt.decode(admin_session, JWT_SECRET, algorithms=[ALGO])
            if payload.get("role") == "admin":
                return True
        except jwt.PyJWTError:
            pass

    raise HTTPException(status_code=403, detail="Not authorized")
