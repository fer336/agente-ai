"""Replays the deterministic promptfoo cases in-process against the eval stack.

The promptfoo CLI never runs in this test suite, so a dataset can silently drift from the
agent's real flow (the v0.44.0 audit found several cases expecting an older flow). This
replays every dataset conversation turn by turn through the same isolated stack
`/internal/eval/chat` uses (fake LLM, in-memory Redis) and evaluates the deterministic
`javascript` assertions of the cases that do not need a real LLM.
"""

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.api.dependencies import internal_eval
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.fake_redis import InMemoryFakeRedis

_EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
_CUSTOM_JS = _EVALS_DIR / "assertions" / "custom.js"
_HELPER = re.compile(r"file://assertions/custom\.js:(\w+)")
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
#: Helpers that grade LLM-built wording: they fail on purpose under the fake LLM.
_WORDING_HELPERS = {"noLeadingGreeting", "mentionsAll", "introDiffersFromPreviousAsk"}
_DATASETS = [
    "appointments",
    "agreements",
    "handoff",
    "safety",
    "adversarial",
    "audio",
    "flows",
    "flows_view_appointment",
    "audit_followups",
    "clinic_topics",
    "location",
]


@pytest.fixture(autouse=True)
def _in_memory_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    internal_eval.get_eval_session_registry.cache_clear()
    redis = InMemoryFakeRedis()
    monkeypatch.setattr(internal_eval, "get_shared_redis_client", lambda: redis)


def _run_node(checks: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to run assertions/custom.js")
    script = (
        f"const m = require({str(_CUSTOM_JS)!r});"
        "const checks = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(checks.map(c => m[c.helper](c.output, "
        "{config: c.config, vars: c.vars}))))"
    )
    result = subprocess.run(
        [node, "-e", script, json.dumps(checks)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _DATASETS)
async def test_deterministic_cases_hold_against_the_current_flow(name: str):
    path = _EVALS_DIR / "datasets" / f"{name}.yaml"
    if not path.is_file():
        pytest.skip(f"{name}.yaml does not exist")
    provider = internal_eval.get_eval_use_case_provider()
    failures: list[str] = []

    for case in yaml.safe_load(path.read_text()):
        variables = case["vars"]
        conversation_id = ConversationId(f"replay-{variables['conversation_id']}")
        result = await provider(conversation_id).execute(
            conversation_id,
            variables["message"],
            now=_NOW,
            button_payload=variables.get("button_payload") or None,
        )
        if (case.get("metadata") or {}).get("requires_real_llm") is True:
            continue
        output = json.dumps(
            {
                "reply_text": result.reply_text,
                "reply_kind": result.reply_kind,
                "node_names": [n.node_name for n in result.node_executions],
                "tool_names": [t.tool_name for t in result.tool_executions],
                "image_url": result.image_url,
                "buttons": [{"id": b.id, "title": b.title} for b in result.buttons],
                "list_rows": [
                    {"id": r.id, "title": r.title, "description": r.description}
                    for r in result.list_rows
                ],
            }
        )
        checks = []
        for assertion in case["assert"]:
            match = _HELPER.fullmatch(assertion.get("value", ""))
            if assertion["type"] != "javascript" or match is None:
                continue
            if match.group(1) in _WORDING_HELPERS:
                continue
            checks.append(
                {
                    "helper": match.group(1),
                    "output": output,
                    "config": assertion.get("config") or {},
                    "vars": variables,
                }
            )
        for check, verdict in zip(checks, _run_node(checks), strict=True):
            if not verdict["pass"]:
                failures.append(f"{case['description']}: {check['helper']} -> {verdict['reason']}")

    assert not failures, "\n".join(failures)
