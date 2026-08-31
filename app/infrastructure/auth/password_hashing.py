import base64
import hashlib
import hmac
import secrets

#: scrypt cost parameters (interactive-login profile — RFC 7914's own
#: recommended minimum). No new dependency needed: `hashlib.scrypt` has
#: shipped in the stdlib since Python 3.6, so this stays consistent with
#: the rest of the codebase's "don't add a dependency the stdlib already
#: covers" bar (see `TranscribeAudioUseCase`'s use of `mutagen` for the one
#: thing the stdlib genuinely can't do, by contrast).
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_LEN = 16

_PREFIX = "scrypt"


def hash_password(password: str) -> str:
    """Hashes `password` into a self-describing `scrypt$n$r$p$salt$hash` string.

    The cost parameters travel with the hash (not just in this module's
    constants) so an already-issued hash keeps verifying correctly even if
    a later change tunes `_N`/`_R`/`_P` for new accounts.
    """
    salt = secrets.token_bytes(_SALT_LEN)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return (
        f"{_PREFIX}${_N}${_R}${_P}"
        f"${base64.urlsafe_b64encode(salt).decode()}"
        f"${base64.urlsafe_b64encode(derived).decode()}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification of `password` against a stored hash.

    Returns `False` (never raises) for a malformed/foreign-format hash —
    an admin-login endpoint must fail closed on a corrupt row, not 500.
    """
    parts = password_hash.split("$")
    if len(parts) != 6 or parts[0] != _PREFIX:
        return False

    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.urlsafe_b64decode(parts[4])
        expected = base64.urlsafe_b64decode(parts[5])
    except ValueError:
        return False

    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
    )
    return hmac.compare_digest(candidate, expected)
