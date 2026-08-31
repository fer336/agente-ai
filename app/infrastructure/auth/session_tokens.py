import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

_SEPARATOR = "|"


@dataclass(frozen=True)
class SessionPayload:
    """Decoded, signature-verified contents of an admin session token.

    `csrf_token_hash` is the sha256 hex digest of the plaintext CSRF token
    handed to the client as a separate, non-`HttpOnly` cookie at login
    (double-submit pattern, PRD.md §74.3) — the plaintext token itself
    never round-trips through this signed payload.
    """

    admin_user_id: str
    username: str
    role: str
    csrf_token_hash: str
    issued_at: datetime
    expires_at: datetime


def create_session_token(
    admin_user_id: str,
    username: str,
    role: str,
    secret: str,
    ttl_seconds: int,
    now: datetime,
) -> tuple[str, str]:
    """Issues a signed, stateless session token plus its paired CSRF token.

    Returns `(session_token, csrf_token)` — the caller sets `session_token`
    as an `HttpOnly`+`Secure`+`SameSite` cookie and `csrf_token` as a
    readable-by-JS cookie the client must echo back in a request header on
    every mutating request (PRD.md §74.3/§75.3's CSRF requirement).

    `admin_user_id`/`username`/`role` are system-controlled account fields
    (never raw user input) and are assumed not to contain the `|`
    separator — `AdminUser.username` is validated at account-creation time,
    not here.
    """
    csrf_token = secrets.token_urlsafe(32)
    csrf_token_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(seconds=ttl_seconds)

    body = _SEPARATOR.join(
        [
            admin_user_id,
            username,
            role,
            csrf_token_hash,
            now.isoformat(),
            expires_at.isoformat(),
        ]
    )
    signature = _sign(body, secret)
    body_b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii")
    return f"{body_b64}.{signature}", csrf_token


def verify_session_token(token: str, secret: str, now: datetime) -> SessionPayload | None:
    """Verifies signature and expiry, returning the payload or `None`.

    Never raises on a missing/tampered/malformed/expired token — every
    failure mode collapses to `None` so callers can respond with a single
    generic 401 (PRD.md §74.3: "respuestas genéricas en fallos de
    autenticación").
    """
    try:
        body_b64, signature = token.split(".", 1)
        body = base64.urlsafe_b64decode(body_b64.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None

    expected_signature = _sign(body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    parts = body.split(_SEPARATOR)
    if len(parts) != 6:
        return None
    admin_user_id, username, role, csrf_token_hash, issued_at_raw, expires_at_raw = parts

    try:
        issued_at = datetime.fromisoformat(issued_at_raw)
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError:
        return None

    if now >= expires_at:
        return None

    return SessionPayload(
        admin_user_id=admin_user_id,
        username=username,
        role=role,
        csrf_token_hash=csrf_token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
