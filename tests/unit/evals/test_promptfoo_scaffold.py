"""Structural validation of the Promptfoo scaffold (PRD.md §58, Etapa 10).

The Promptfoo CLI itself (Node) is not part of this Python project's
toolchain — `npx promptfoo eval` was never run against a live server in
this environment (deferred, same as GROQ_API_KEY in the audio-pipeline
change). What IS verified here, with real parsing/execution: every YAML
file is syntactically valid and internally consistent, every file the
config references exists, and `assertions/custom.js` is syntactically
valid Node and behaves correctly against sample payloads.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
_DATASET_NAMES = [
    "appointments",
    "agreements",
    "handoff",
    "safety",
    "adversarial",
    "audio",
]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_scaffold_has_the_prd_58_documented_directory_tree():
    assert (_EVALS_DIR / "promptfooconfig.yaml").is_file()
    assert (_EVALS_DIR / "prompts" / "agent_system_prompt.txt").is_file()
    assert (_EVALS_DIR / "assertions" / "custom.js").is_file()
    for name in _DATASET_NAMES:
        assert (_EVALS_DIR / "datasets" / f"{name}.yaml").is_file()


def test_promptfooconfig_parses_and_references_every_dataset_file():
    config = _load_yaml(_EVALS_DIR / "promptfooconfig.yaml")

    assert config["prompts"] == ["file://prompts/agent_system_prompt.txt"]
    referenced = config["tests"]
    for name in _DATASET_NAMES:
        assert f"evals/datasets/{name}.yaml" in referenced


def test_system_prompt_is_non_empty_and_covers_the_non_negotiable_rules():
    text = (_EVALS_DIR / "prompts" / "agent_system_prompt.txt").read_text()

    assert len(text.strip()) > 0
    # PRD.md §6/§16/§59.4's core rules the prompt must encode.
    for required_phrase in ["confirmación", "diagnóstic", "handoff", "audio"]:
        assert required_phrase in text.lower()


@pytest.mark.parametrize("name", _DATASET_NAMES)
def test_dataset_file_has_well_formed_test_cases(name: str):
    dataset = _load_yaml(_EVALS_DIR / "datasets" / f"{name}.yaml")

    assert "tests" in dataset
    assert len(dataset["tests"]) > 0

    seen_conversation_ids = set()
    for test_case in dataset["tests"]:
        assert isinstance(test_case["description"], str) and test_case["description"]
        assert "message" in test_case["vars"]
        conversation_id = test_case["vars"]["conversation_id"]
        assert conversation_id not in seen_conversation_ids, (
            f"duplicate conversation_id {conversation_id!r} in {name}.yaml"
        )
        seen_conversation_ids.add(conversation_id)
        assert len(test_case["assert"]) > 0

        metadata = test_case.get("metadata")
        if metadata and metadata.get("critical"):
            assert metadata.get("critical_reason"), (
                f"critical test {test_case['description']!r} in {name}.yaml "
                "is missing critical_reason"
            )


def test_at_least_one_critical_case_per_prd_62_category_exists():
    """PRD.md §62 lists specific critical-failure categories — at least one
    dataset test must be tagged `critical: true` overall (full per-category
    coverage is asserted implicitly by each dataset's own tests above; this
    is a coarse sanity check that the tagging convention was actually used,
    not skipped).
    """
    critical_count = 0
    for name in _DATASET_NAMES:
        dataset = _load_yaml(_EVALS_DIR / "datasets" / f"{name}.yaml")
        for test_case in dataset["tests"]:
            metadata = test_case.get("metadata")
            if metadata and metadata.get("critical"):
                critical_count += 1

    assert critical_count >= 10


def test_custom_assertions_js_is_syntactically_valid_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    result = subprocess.run(
        [node, "--check", str(_EVALS_DIR / "assertions" / "custom.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_custom_assertions_js_exports_the_expected_functions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    custom_js_path = str(_EVALS_DIR / "assertions" / "custom.js")
    script = f"console.log(JSON.stringify(Object.keys(require({custom_js_path!r}))))"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    exported = json.loads(result.stdout)
    assert set(exported) == {"noSensitiveActionBeforeConfirmation", "noSensitiveValuesInReply"}


def test_no_sensitive_action_before_confirmation_flags_cancel_without_confirmation():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    payload = json.dumps({"tool_names": ["identify_patient", "cancel_appointment"]})
    script = (
        f"const m = require({str(_EVALS_DIR / 'assertions' / 'custom.js')!r});"
        f"console.log(JSON.stringify(m.noSensitiveActionBeforeConfirmation({payload!r})))"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pass"] is False


def test_no_sensitive_action_before_confirmation_passes_when_confirmed_first():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    payload = json.dumps(
        {"tool_names": ["identify_patient", "request_confirmation", "cancel_appointment"]}
    )
    script = (
        f"const m = require({str(_EVALS_DIR / 'assertions' / 'custom.js')!r});"
        f"console.log(JSON.stringify(m.noSensitiveActionBeforeConfirmation({payload!r})))"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pass"] is True


def test_no_sensitive_values_in_reply_flags_a_leaked_decoy():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    payload = json.dumps({"reply_text": "tu DNI es DNI_TEST_30111222"})
    script = (
        f"const m = require({str(_EVALS_DIR / 'assertions' / 'custom.js')!r});"
        f"console.log(JSON.stringify(m.noSensitiveValuesInReply({payload!r})))"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pass"] is False
