"""Static checks only: the audit script is never executed here."""

import os
import re
from pathlib import Path

_EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
_SCRIPT = _EVALS_DIR / "run-audit.sh"
_PRELOAD = _EVALS_DIR / "localhost-only.cjs"


def test_script_exists_and_is_executable():
    assert _SCRIPT.is_file()
    assert os.access(_SCRIPT, os.X_OK)


def test_script_fails_fast():
    assert "set -euo pipefail" in _SCRIPT.read_text()


def test_script_never_puts_secrets_in_argv_or_output():
    text = _SCRIPT.read_text()
    assert not re.search(r'--data\s+"', text)
    assert "--data @-" in text
    assert not re.search(r'echo\s+"?\$\{?\w*KEY', text)
    assert "read -r -s" in text
    assert "unset ADMIN_PASSWORD" in text


def test_script_cleans_up_the_cookie_jar_and_disables_telemetry():
    text = _SCRIPT.read_text()
    assert "chmod 600" in text
    assert "trap cleanup EXIT" in text
    assert "PROMPTFOO_DISABLE_TELEMETRY=1" in text
    assert "PROMPTFOO_DISABLE_SHARING=1" in text


def test_view_mode_uses_the_localhost_only_preload():
    text = _SCRIPT.read_text()
    assert "--view" in text
    assert "localhost-only.cjs" in text
    assert "ssh -N -L" in text


def test_preload_forces_loopback_binding():
    text = _PRELOAD.read_text()
    assert "127.0.0.1" in text
    assert "net.Server.prototype.listen" in text
