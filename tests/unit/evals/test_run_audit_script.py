"""The audit script is never executed here; its decision logic lives in a helper we run."""

import importlib.util
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
_README = _EVALS_DIR / "README.md"
_HELPER = _EVALS_DIR / "check_grader_host.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("check_grader_host", _HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(_HELPER), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
    )


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


def test_backend_technical_role_constant_matches_the_script():
    assert ADMIN_TECHNICAL == "ADMIN_TECHNICAL"
    assert '"ADMIN_TECHNICAL"' in _SCRIPT.read_text()


def test_role_check_uppercases_portably_without_bash4_expansion():
    text = _SCRIPT.read_text()
    assert "${ROLE^^}" not in text
    assert "tr '[:lower:]' '[:upper:]'" in text


def test_promptfoo_is_pinned_to_an_exact_version_for_eval_and_view():
    text = _SCRIPT.read_text()
    assert re.search(r'PROMPTFOO_VERSION="\$\{PROMPTFOO_VERSION:-\d+\.\d+\.\d+\}"', text)
    assert "promptfoo@latest" not in text
    assert text.count('"promptfoo@${PROMPTFOO_VERSION}"') == 2


_ALLOWED = "https://openrouter.ai/api/v1"


def test_script_delegates_the_host_check_and_quote_strip_to_the_helper():
    text = _SCRIPT.read_text()
    assert "check_grader_host.py" in text
    assert "sed -E" not in text
    assert "shares the production" in text


@pytest.mark.parametrize(
    "url",
    [
        _ALLOWED,
        "https://OpenRouter.AI/api/v1",
        "https://openrouter.ai",
        "https://openrouter.ai:443/api/v1",
    ],
)
def test_helper_allows_the_openrouter_host_over_https(url):
    result = _cli("check", url, "--key-from-secret")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "url",
    [
        "https://openrouter.ai:x@evil.example/v1",
        "https://user@openrouter.ai/v1",
        "https://user:pw@openrouter.ai/v1",
        "http://openrouter.ai/api/v1",
        "https://evil.example/api/v1",
        "https://openrouter.ai.evil.com/api/v1",
        "https://evilopenrouter.ai/api/v1",
        "ftp://openrouter.ai/api/v1",
        "openrouter.ai/api/v1",
        "",
    ],
)
def test_helper_refuses_bypass_attempts_for_an_auto_read_key(url):
    result = _cli("check", url, "--key-from-secret")
    assert result.returncode != 0
    assert "Refusing to send the backend's key" in result.stderr
    assert "EVAL_GRADER_API_KEY" in result.stderr


def test_explicit_key_bypasses_the_allowlist():
    result = _cli("check", "https://evil.example/v1")
    assert result.returncode == 0, result.stderr


def test_helper_check_function_matches_the_cli_decision():
    helper = _load_helper()
    assert helper.is_allowed_grader_url(_ALLOWED)
    assert not helper.is_allowed_grader_url("https://openrouter.ai:x@evil.example/v1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"abc"', "abc"),
        ("'abc'", "abc"),
        ('"a"b"', 'a"b'),
        ("'a'b'", "a'b"),
        ('""abc""', '"abc"'),
        ("abc", "abc"),
        ('"abc', '"abc'),
        ("abc'", "abc'"),
        ("\"abc'", "\"abc'"),
        ('"', '"'),
        ("", ""),
    ],
)
def test_strip_surrounding_quotes_removes_exactly_one_matching_pair(raw, expected):
    assert _load_helper().strip_surrounding_quotes(raw) == expected


def test_strip_quotes_cli_reads_stdin_and_adds_no_newline():
    result = _cli("strip-quotes", stdin='"sk-a"b"')
    assert result.returncode == 0
    assert result.stdout == 'sk-a"b'


def test_script_prints_the_session_expiry_note_using_the_ttl_override():
    text = _SCRIPT.read_text()
    assert "${ADMIN_SESSION_TTL_SECONDS:-3600}" in text
    assert "date -d" not in text
    assert "401" in text


def test_no_floating_promptfoo_tag_in_script_or_readme():
    assert "@latest" not in _SCRIPT.read_text()
    assert "@latest" not in _README.read_text()


def test_readme_describes_the_pinned_version_not_a_stale_command():
    text = _README.read_text()
    assert "promptfoo@${PROMPTFOO_VERSION}" in text


def test_no_9router_default_remains_in_script_or_readme():
    assert "9router" not in _SCRIPT.read_text().lower()
    assert "9router" not in _README.read_text().lower()
    assert "https://openrouter.ai/api/v1" in _SCRIPT.read_text()


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
