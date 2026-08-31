import base64
import hashlib
from datetime import UTC, datetime, timedelta

import app.infrastructure.auth.session_tokens as session_tokens_module
from app.domain.entities.admin_user import ADMIN_TECHNICAL
from app.infrastructure.auth.session_tokens import create_session_token, verify_session_token


def _signed_token(body: str, secret: str) -> str:
    """Builds a correctly-SIGNED token around an arbitrary (possibly
    malformed) `body`, so `verify_session_token`'s body-parsing failure
    branches can be exercised past signature verification.
    """
    signature = session_tokens_module._sign(body, secret)
    body_b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii")
    return f"{body_b64}.{signature}"

_SECRET = "test-session-secret"
_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


def test_verify_session_token_accepts_a_freshly_issued_token():
    token, _csrf = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, ttl_seconds=3600, now=_NOW
    )

    payload = verify_session_token(token, _SECRET, now=_NOW)

    assert payload is not None
    assert payload.admin_user_id == "admin-1"
    assert payload.username == "tech1"
    assert payload.role == ADMIN_TECHNICAL


def test_verify_session_token_embeds_the_csrf_token_hash_not_the_plaintext():
    token, csrf_token = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, ttl_seconds=3600, now=_NOW
    )

    payload = verify_session_token(token, _SECRET, now=_NOW)

    assert payload is not None
    assert payload.csrf_token_hash == hashlib.sha256(csrf_token.encode()).hexdigest()
    assert csrf_token not in token


def test_verify_session_token_rejects_an_expired_token():
    token, _csrf = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, ttl_seconds=60, now=_NOW
    )

    payload = verify_session_token(token, _SECRET, now=_NOW + timedelta(seconds=61))

    assert payload is None


def test_verify_session_token_rejects_a_tampered_signature():
    token, _csrf = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, ttl_seconds=3600, now=_NOW
    )
    body, _signature = token.split(".", 1)
    tampered = f"{body}.0000000000000000000000000000000000000000000000000000000000000000"

    assert verify_session_token(tampered, _SECRET, now=_NOW) is None


def test_verify_session_token_rejects_a_token_signed_with_a_different_secret():
    token, _csrf = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, ttl_seconds=3600, now=_NOW
    )

    assert verify_session_token(token, "different-secret", now=_NOW) is None


def test_verify_session_token_rejects_garbage_input():
    assert verify_session_token("not-a-real-token", _SECRET, now=_NOW) is None
    assert verify_session_token("", _SECRET, now=_NOW) is None
    assert verify_session_token("a.b.c", _SECRET, now=_NOW) is None


def test_verify_session_token_rejects_a_body_with_the_wrong_field_count():
    token = _signed_token("only|four|fields|here", _SECRET)

    assert verify_session_token(token, _SECRET, now=_NOW) is None


def test_verify_session_token_rejects_an_unparseable_date():
    body = "|".join(["user-1", "admin", ADMIN_TECHNICAL, "hash", "not-a-date", "not-a-date"])
    token = _signed_token(body, _SECRET)

    assert verify_session_token(token, _SECRET, now=_NOW) is None
