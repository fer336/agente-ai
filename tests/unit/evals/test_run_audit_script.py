"""Static checks only: the audit script is never executed here."""

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from app.domain.entities.admin_user import ADMIN_TECHNICAL

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


def test_backend_technical_role_constant_matches_the_script_and_readme():
    assert ADMIN_TECHNICAL == "ADMIN_TECHNICAL"
    assert '"ADMIN_TECHNICAL"' in _SCRIPT.read_text()


def test_role_check_is_case_insensitive():
    assert "${ROLE^^}" in _SCRIPT.read_text()


def test_promptfoo_is_pinned_to_an_exact_version_for_eval_and_view():
    text = _SCRIPT.read_text()
    assert re.search(r'PROMPTFOO_VERSION="\$\{PROMPTFOO_VERSION:-\d+\.\d+\.\d+\}"', text)
    assert "promptfoo@latest" not in text
    assert text.count('"promptfoo@${PROMPTFOO_VERSION}"') == 2


def test_auto_read_grader_key_is_restricted_to_an_allowlisted_host():
    text = _SCRIPT.read_text()
    assert "openrouter.ai" in text
    assert "ALLOWED_SECRET_KEY_HOSTS" in text
    assert "shares the production" in text


def test_script_prints_the_session_expiry_note():
    text = _SCRIPT.read_text()
    assert "ADMIN_SESSION_TTL_SECONDS" in text
    assert "401" in text


def test_backend_secret_quote_strip_is_surrounding_only():
    text = _SCRIPT.read_text()
    assert "tr -d" not in text


def test_help_exits_zero_and_prints_usage():
    result = subprocess.run(
        ["bash", str(_SCRIPT), "--help"], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0
    assert "Usage: evals/run-audit.sh" in result.stdout


def test_unknown_argument_exits_two_with_usage_on_stderr():
    result = subprocess.run(
        ["bash", str(_SCRIPT), "--nope"], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 2
    assert "Unknown argument" in result.stderr
    assert "Usage: evals/run-audit.sh" in result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_preload_binds_every_listen_form_to_loopback():
    node = shutil.which("node")
    assert node is not None
    script = textwrap.dedent(
        """
        const net = require('net');
        const forms = {
          noArgs: (s) => s.listen(),
          callbackOnly: (s, cb) => s.listen(cb),
          port: (s, cb) => s.listen(0, cb),
          portString: (s, cb) => s.listen('0', cb),
          portHost: (s, cb) => s.listen(0, '0.0.0.0', cb),
          portHostBacklog: (s, cb) => s.listen(0, '0.0.0.0', 16, cb),
          portBacklog: (s, cb) => s.listen(0, 16, cb),
          options: (s, cb) => s.listen({ port: 0, host: '0.0.0.0' }, cb),
          optionsNoHost: (s, cb) => s.listen({ port: 0 }, cb),
        };
        (async () => {
          const out = {};
          for (const [name, listen] of Object.entries(forms)) {
            const server = net.createServer();
            await new Promise((resolve, reject) => {
              server.once('error', reject);
              server.once('listening', resolve);
              listen(server, () => {});
            });
            out[name] = server.address().address;
            server.close();
          }
          console.log(JSON.stringify(out));
        })().catch((e) => { console.error(e); process.exit(1); });
        """
    )
    result = subprocess.run(
        [node, "--require", str(_PRELOAD), "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    import json

    bound = json.loads(result.stdout)
    assert len(bound) == 9
    assert set(bound.values()) == {"127.0.0.1"}
