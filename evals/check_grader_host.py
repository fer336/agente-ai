#!/usr/bin/env python3
"""Decision helpers for evals/run-audit.sh (kept in Python so they are testable).

CLI:
  check_grader_host.py check URL [--key-from-secret]   exit 1 if refused
  check_grader_host.py strip-quotes                    stdin -> stdout, no newline
"""

import sys
from urllib.parse import urlsplit

ALLOWED_SECRET_KEY_HOSTS = frozenset({"openrouter.ai"})


def is_allowed_grader_url(url: str) -> bool:
    """True only for https URLs without userinfo whose exact host is allowlisted."""
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname
        has_userinfo = "@" in parts.netloc
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or has_userinfo or not hostname:
        return False
    return hostname.lower() in ALLOWED_SECRET_KEY_HOSTS


def strip_surrounding_quotes(value: str) -> str:
    """Remove exactly one matching pair of surrounding quotes; keep inner ones."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def main(argv: list[str]) -> int:
    if argv[:1] == ["strip-quotes"]:
        sys.stdout.write(strip_surrounding_quotes(sys.stdin.read()))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        url, flags = argv[1], argv[2:]
        if "--key-from-secret" not in flags or is_allowed_grader_url(url):
            return 0
        allowed = ", ".join(sorted(ALLOWED_SECRET_KEY_HOSTS))
        sys.stderr.write(
            "Refusing to send the backend's key to the grader URL "
            f"(https, no userinfo, host must be one of: {allowed}).\n"
            "Set EVAL_GRADER_API_KEY explicitly to use another grader host.\n"
        )
        return 1
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
