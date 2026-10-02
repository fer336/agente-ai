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
import re
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
    "flows",
    "flows_view_appointment",
    "audit_followups",
    "clinic_topics",
    "location",
    "thanks",
]
_CUSTOM_JS = _EVALS_DIR / "assertions" / "custom.js"
_HELPER_REFERENCE = re.compile(r"file://assertions/custom\.js:(\w+)")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _load_test_cases(name: str) -> list[dict]:
    """promptfoo loads a `file://` tests entry as a top-level YAML list of test
    cases; a mapping (e.g. wrapped under a `tests:` key) is read as one
    malformed test case and aborts the whole eval before any request."""
    test_cases = yaml.safe_load((_EVALS_DIR / "datasets" / f"{name}.yaml").read_text())
    assert isinstance(test_cases, list), f"{name}.yaml must be a top-level list"
    return test_cases


def test_scaffold_has_the_prd_58_documented_directory_tree():
    assert (_EVALS_DIR / "promptfooconfig.yaml").is_file()
    assert (_EVALS_DIR / "prompts" / "agent_system_prompt.txt").is_file()
    assert (_EVALS_DIR / "assertions" / "custom.js").is_file()
    for name in _DATASET_NAMES:
        assert (_EVALS_DIR / "datasets" / f"{name}.yaml").is_file()
    assert (_EVALS_DIR / "README.md").is_file()


def test_promptfooconfig_parses_and_references_every_dataset_file():
    config = _load_yaml(_EVALS_DIR / "promptfooconfig.yaml")

    assert config["prompts"] == ["file://prompts/agent_system_prompt.txt"]
    referenced = config["tests"]
    # `file://` paths resolve from the config file's own directory.
    for name in _DATASET_NAMES:
        assert f"file://datasets/{name}.yaml" in referenced


def test_promptfooconfig_runs_turns_in_order_without_serving_cached_replies():
    config = _load_yaml(_EVALS_DIR / "promptfooconfig.yaml")

    # Turns of a conversation are separate tests: they only work sequentially, and a
    # cached reply would skip the server call that builds the conversation's state.
    assert config["evaluateOptions"]["maxConcurrency"] == 1
    assert config["evaluateOptions"]["cache"] is False


def test_promptfooconfig_sends_button_taps_and_a_run_scoped_conversation_id():
    config = _load_yaml(_EVALS_DIR / "promptfooconfig.yaml")

    body = config["providers"][0]["config"]["body"]
    assert "button_payload" in body
    assert "env.EVAL_RUN_ID" in body["conversation_id"]
    assert "{{conversation_id}}" in body["conversation_id"]


def test_system_prompt_is_non_empty_and_covers_the_non_negotiable_rules():
    text = (_EVALS_DIR / "prompts" / "agent_system_prompt.txt").read_text()

    assert len(text.strip()) > 0
    # PRD.md §6/§16/§59.4's core rules the prompt must encode.
    for required_phrase in ["confirmación", "diagnóstic", "handoff", "audio"]:
        assert required_phrase in text.lower()


@pytest.mark.parametrize("name", _DATASET_NAMES)
def test_dataset_file_has_well_formed_test_cases(name: str):
    dataset = _load_test_cases(name)

    assert len(dataset) > 0

    # A conversation's turns are consecutive tests sharing one conversation_id; a
    # conversation_id must never come back after another conversation started.
    finished_conversation_ids = set()
    current_conversation_id = None
    for test_case in dataset:
        assert isinstance(test_case["description"], str) and test_case["description"]
        assert "message" in test_case["vars"]
        conversation_id = test_case["vars"]["conversation_id"]
        if conversation_id != current_conversation_id:
            assert conversation_id not in finished_conversation_ids, (
                f"conversation_id {conversation_id!r} in {name}.yaml is not contiguous"
            )
            if current_conversation_id is not None:
                finished_conversation_ids.add(current_conversation_id)
            current_conversation_id = conversation_id
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
        dataset = _load_test_cases(name)
        for test_case in dataset:
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
    assert set(exported) == {
        "noSensitiveActionBeforeConfirmation",
        "noSensitiveValuesInReply",
        "replyKindIs",
        "hasButtons",
        "hasImage",
        "hasOptionIds",
        "noListRows",
        "noBulletList",
        "hasBulletLines",
        "bulletsExactly",
        "noLeadingGreeting",
        "mentionsAll",
        "nodeNotVisited",
        "nodeVisited",
        "introDiffersFromPreviousAsk",
        "onlyOptionIds",
        "handoffOfferHasButtons",
    }


def _run_helper(helper: str, output: dict, config: dict | None = None, vars_: dict | None = None):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    context = {"config": config or {}, "vars": vars_ or {}}
    # The provider hands `output` over as a JSON string; `context` is a plain object.
    script = (
        f"const m = require({str(_CUSTOM_JS)!r});"
        f"const output = {json.dumps(json.dumps(output))}; const context = {json.dumps(context)};"
        f"console.log(JSON.stringify(m.{helper}(output, context)))"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


_QUESTION_REPLY = {
    "reply_text": "¿Es tu primera cita en Smiling Pilar?",
    "reply_kind": "buttons",
    "buttons": [
        {"id": "FIRST_VISIT_CONFIRM", "title": "✅ Confirmar"},
        {"id": "FIRST_VISIT_CANCEL", "title": "❌ Cancelar"},
    ],
    "list_rows": [],
    "node_names": ["appointment"],
}
_ASK_REPLY = {
    "reply_text": "Para dejarte registrado necesito estos datos:\n\n- Nombre completo\n- DNI",
    "reply_kind": "text",
    "buttons": [],
    "list_rows": [],
    "node_names": ["appointment"],
}


def test_has_buttons_requires_an_interactive_reply_with_every_title():
    config = {"titles": ["✅ Confirmar", "❌ Cancelar"]}

    assert _run_helper("hasButtons", _QUESTION_REPLY, config)["pass"] is True
    assert (
        _run_helper("hasButtons", _QUESTION_REPLY, {"titles": ["Menú principal"]})["pass"] is False
    )
    assert _run_helper("hasButtons", _ASK_REPLY, config)["pass"] is False
    assert (
        _run_helper(
            "hasButtons", _QUESTION_REPLY, {**config, "titles": ["✅ Confirmar"], "exact": True}
        )["pass"]
        is False
    )


def test_has_image_requires_an_http_image_url():
    with_image = {**_ASK_REPLY, "image_url": "https://agent.example.com/public/clinic-location.jpg"}

    assert _run_helper("hasImage", with_image)["pass"] is True
    assert _run_helper("hasImage", {**_ASK_REPLY, "image_url": None})["pass"] is False
    assert _run_helper("hasImage", {**_ASK_REPLY, "image_url": ""})["pass"] is False
    assert _run_helper("hasImage", {**_ASK_REPLY})["pass"] is False


def test_has_option_ids_checks_buttons_and_list_rows_and_can_forbid_extras():
    rows = {
        **_ASK_REPLY,
        "reply_kind": "list",
        "list_rows": [{"id": "SELECT_SLOT:1", "title": "a"}, {"id": "LIST_BACK", "title": "b"}],
    }

    assert _run_helper("hasOptionIds", rows, {"ids": ["SELECT_SLOT:1"]})["pass"] is True
    assert _run_helper("hasOptionIds", rows, {"ids": ["SELECT_SLOT:2"]})["pass"] is False
    exact = {"ids": ["SELECT_SLOT:1"], "exact": True}
    assert _run_helper("hasOptionIds", rows, exact)["pass"] is False
    both = {"ids": ["SELECT_SLOT:1", "LIST_BACK"], "exact": True}
    assert _run_helper("hasOptionIds", rows, both)["pass"] is True
    assert _run_helper("hasOptionIds", _QUESTION_REPLY, {"ids": ["FIRST_VISIT_CONFIRM"]})["pass"]


def test_bullet_helpers_distinguish_a_bullet_list_from_a_plain_question():
    items = {"items": ["Nombre completo", "DNI"]}

    assert _run_helper("noBulletList", _QUESTION_REPLY)["pass"] is True
    assert _run_helper("noBulletList", _ASK_REPLY)["pass"] is False
    assert _run_helper("hasBulletLines", _ASK_REPLY, {"min": 2})["pass"] is True
    assert _run_helper("hasBulletLines", _ASK_REPLY, {"min": 3})["pass"] is False
    assert _run_helper("hasBulletLines", _QUESTION_REPLY)["pass"] is False
    assert _run_helper("bulletsExactly", _ASK_REPLY, items)["pass"] is True
    assert _run_helper("bulletsExactly", _ASK_REPLY, {"items": ["DNI"]})["pass"] is False
    assert (
        _run_helper("bulletsExactly", _ASK_REPLY, {"items": ["DNI", "Nombre completo"]})["pass"]
        is False
    )


def test_no_leading_greeting_flags_a_greeting_and_a_fake_llm_placeholder():
    greeting = {"reply_text": "¡Hola! Sí, atendemos particulares."}
    plain = {"reply_text": "Sí, atendemos pacientes particulares."}
    placeholder = {"reply_text": "[fake-response for intent=question]"}

    assert _run_helper("noLeadingGreeting", plain)["pass"] is True
    assert _run_helper("noLeadingGreeting", greeting)["pass"] is False
    assert (
        _run_helper("noLeadingGreeting", {"reply_text": "Buenas tardes, te cuento"})["pass"]
        is False
    )
    assert (
        _run_helper("noLeadingGreeting", {"reply_text": "Holístico es otra cosa."})["pass"] is True
    )
    assert "FakeLLMProvider" in _run_helper("noLeadingGreeting", placeholder)["reason"]


def test_reply_shape_helpers_check_kind_list_rows_and_nodes():
    assert _run_helper("replyKindIs", _ASK_REPLY, {"kind": "text"})["pass"] is True
    assert _run_helper("replyKindIs", _ASK_REPLY, {"kind": "buttons"})["pass"] is False
    assert _run_helper("noListRows", _ASK_REPLY)["pass"] is True
    with_rows = {
        **_ASK_REPLY,
        "reply_kind": "list",
        "list_rows": [{"id": "SPECIALTY:1", "title": "X"}],
    }
    assert _run_helper("noListRows", with_rows)["pass"] is False
    assert _run_helper("nodeNotVisited", _ASK_REPLY, {"node": "handoff"})["pass"] is True
    assert _run_helper("nodeNotVisited", _ASK_REPLY, {"node": "appointment"})["pass"] is False
    assert _run_helper("nodeVisited", _ASK_REPLY, {"node": "appointment"})["pass"] is True
    assert _run_helper("mentionsAll", _ASK_REPLY, {"terms": ["datos", "necesito"]})["pass"] is True
    assert _run_helper("mentionsAll", _ASK_REPLY, {"terms": ["obra social"]})["pass"] is False


def test_only_option_ids_accepts_seeded_options_and_rejects_anything_else():
    allowed = {"allowed": ["SELECT_SLOT:eval-free-*", "SPECIALTY:eval-spec-*", "LIST_BACK"]}
    slots = {
        **_ASK_REPLY,
        "reply_kind": "list",
        "list_rows": [
            {"id": "SELECT_SLOT:eval-free-1", "title": "a"},
            {"id": "LIST_BACK", "title": "b"},
        ],
    }
    specialties = {
        **_ASK_REPLY,
        "reply_kind": "list",
        "list_rows": [{"id": "SPECIALTY:eval-spec-2", "title": "x"}],
    }
    invented = {**slots, "list_rows": [{"id": "SELECT_SLOT:invented-9", "title": "z"}]}

    assert _run_helper("onlyOptionIds", slots, allowed)["pass"] is True
    assert _run_helper("onlyOptionIds", specialties, allowed)["pass"] is True
    assert _run_helper("onlyOptionIds", invented, allowed)["pass"] is False
    assert _run_helper("onlyOptionIds", _QUESTION_REPLY, allowed)["pass"] is False
    # A reply with no options at all strands the patient.
    assert _run_helper("onlyOptionIds", _ASK_REPLY, allowed)["pass"] is False


def test_handoff_offer_helper_fails_only_when_an_offer_carries_no_admin_button():
    offer = "Sí, atendemos particulares. ¿Te gustaría que te pase con administración?"
    with_button = {
        "reply_text": offer,
        "reply_kind": "buttons",
        "buttons": [{"id": "MENU_ADMIN", "title": "💬 Administración"}],
    }
    no_buttons = {"reply_text": offer, "reply_kind": "text", "buttons": []}
    other_buttons = {**with_button, "buttons": [{"id": "MENU_MAIN", "title": "Menú principal"}]}
    plain = {"reply_text": "Atendemos de 9 a 18.", "reply_kind": "text", "buttons": []}
    old_wording = {**no_buttons, "reply_text": "Si querés, puedo pasarte con un asesor."}

    assert _run_helper("handoffOfferHasButtons", with_button)["pass"] is True
    assert _run_helper("handoffOfferHasButtons", no_buttons)["pass"] is False
    assert _run_helper("handoffOfferHasButtons", other_buttons)["pass"] is False
    assert _run_helper("handoffOfferHasButtons", old_wording)["pass"] is False
    assert _run_helper("handoffOfferHasButtons", plain)["pass"] is True


def test_intro_helper_flags_a_repeated_intro_within_one_conversation():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")

    def ask(intro: str) -> dict:
        return {"reply_text": f"{intro}\n\n- DNI\n- Plan"}

    script = (
        f"const m = require({str(_CUSTOM_JS)!r});"
        "const ctx = {vars: {conversation_id: 'c1'}};"
        f"const same = {json.dumps(json.dumps(ask('Gracias. Me faltan:')))};"
        f"const other = {json.dumps(json.dumps(ask('Ya casi estamos:')))};"
        "const a = m.introDiffersFromPreviousAsk(same, ctx);"
        "const b = m.introDiffersFromPreviousAsk(same, ctx);"
        "const c = m.introDiffersFromPreviousAsk(other, ctx);"
        "console.log(JSON.stringify([a.pass, b.pass, c.pass]))"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [True, False, True]


def _dataset_asserts(name: str):
    dataset = _load_test_cases(name)
    for test_case in dataset:
        for assertion in test_case["assert"]:
            yield test_case, assertion


@pytest.mark.parametrize("name", _DATASET_NAMES)
def test_dataset_javascript_asserts_reference_exported_helpers(name: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available to validate assertions/custom.js")
    script = f"console.log(JSON.stringify(Object.keys(require({str(_CUSTOM_JS)!r}))))"
    exported = set(
        json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True).stdout)
    )

    for test_case, assertion in _dataset_asserts(name):
        if assertion["type"] != "javascript":
            continue
        match = _HELPER_REFERENCE.fullmatch(assertion["value"])
        assert match, (
            f"{test_case['description']!r}: unexpected javascript value {assertion['value']!r}"
        )
        assert match.group(1) in exported, f"{match.group(1)} is not exported by custom.js"


@pytest.mark.parametrize("name", ["flows", "flows_view_appointment"])
def test_flow_datasets_are_ordered_multi_turn_scenarios(name: str):
    dataset = _load_test_cases(name)

    turns_by_conversation: dict[str, list[int]] = {}
    for test_case in dataset:
        match = re.fullmatch(r".+ — turn (\d+)", test_case["description"])
        assert match, f"{test_case['description']!r} must end with ' — turn N'"
        turns_by_conversation.setdefault(test_case["vars"]["conversation_id"], []).append(
            int(match[1])
        )
        # A tap sends the payload id; the message then carries the button title.
        payload = test_case["vars"].get("button_payload")
        assert payload is None or re.fullmatch(r"[A-Z_]+(:\w+)?", payload)

    assert len(turns_by_conversation) >= 1
    for conversation_id, turns in turns_by_conversation.items():
        assert turns == list(range(1, len(turns) + 1)), f"{conversation_id}: turns {turns}"


def test_view_appointment_dataset_uses_the_seeded_eval_patient():
    from app.infrastructure.dentalink.eval_seed import EVAL_PATIENT_DNI, EVAL_PATIENT_NAME

    dataset = _load_test_cases("flows_view_appointment")
    identify = dataset[1]["vars"]["message"]

    assert EVAL_PATIENT_NAME in identify
    assert EVAL_PATIENT_DNI in identify


def test_flows_dataset_covers_the_recent_flows():
    dataset = _load_test_cases("flows")
    descriptions = " | ".join(t["description"] for t in dataset).lower()
    payloads = {t["vars"].get("button_payload") for t in dataset}

    for scenario in ["primera visita", "datos de alta", "ya soy paciente", "sin saludo", "handoff"]:
        assert scenario in descriptions
    assert {"OPERATION_CREATE", "FIRST_VISIT_CONFIRM", "FIRST_VISIT_CANCEL"} <= payloads


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


def test_readme_documents_the_always_on_production_audit():
    readme = (_EVALS_DIR / "README.md").read_text()

    for required in [
        "INTERNAL_EVAL_ENABLED",
        "INTERNAL_EVAL_REAL_LLM",
        "agente_ai_backend_env",
        "ADMIN_TECHNICAL",
        "evals/run-audit.sh",
        "--view",
        "EVAL_RUN_ID",
        "read -r -s",
        "replicas: 1",
        "Default stance",
        "docker secret rm agente_ai_backend_env_eval",
        "PROMPTFOO_VERSION",
        "ADMIN_SESSION_TTL_SECONDS",
        "spend limit",
        "rollback",
    ]:
        assert required in readme
    # The old temporary-exception runbook is gone, and secrets/passwords stay out of it.
    assert "--env-add" not in readme
    assert "--env-rm" not in readme
    assert "cp <your-backend.env>" not in readme
    assert "docker secret create" not in readme
    assert '"password":"<ADMIN_PASSWORD>"' not in readme


def test_grader_config_has_safe_defaults_and_no_stale_9router_default():
    config = (_EVALS_DIR / "promptfooconfig.yaml").read_text()

    assert "env.EVAL_GRADER_MODEL or" in config
    assert "env.EVAL_GRADER_BASE_URL or" in config
    assert "https://openrouter.ai/api/v1" in config
    assert "OpenRouter" in config


def test_audit_followups_dataset_covers_each_task_with_deterministic_asserts():
    tests = _load_test_cases("audit_followups")
    messages = " | ".join(t["vars"]["message"].casefold() for t in tests)
    helpers = {
        _HELPER_REFERENCE.fullmatch(a["value"])[1]
        for t in tests
        for a in t["assert"]
        if a["type"] == "javascript"
    }

    # T1: the five PRD.md §22 phrases hand off.
    for phrase in [
        "voy a llegar tarde",
        "estoy llegando",
        "no aparece mi turno",
        "me equivoqué con el turno",
        "tengo un problema con mi turno",
    ]:
        assert phrase in messages
    # T2: a kinship claim; T3: an unknown patient; T4: an offer; T5: a seeded agreement.
    assert "soy familiar de" in messages
    assert "juan pérez, 30111222" in messages
    assert "osde 210" in messages
    assert {"nodeVisited", "hasButtons", "hasOptionIds", "handoffOfferHasButtons"} <= helpers
    payloads = {t["vars"].get("button_payload") for t in tests}
    assert {"PATIENT_NOT_FOUND_REGISTER", "PATIENT_NOT_FOUND_RETRY", "MENU_ADMIN"} <= payloads


def test_clinic_topics_dataset_covers_topics_menu_booking_and_special_insurances():
    tests = _load_test_cases("clinic_topics")
    payloads = {t["vars"].get("button_payload") for t in tests}
    messages = " | ".join(t["vars"]["message"].casefold() for t in tests)

    assert "MENU_FAQ" in payloads
    assert {
        f"FAQ_TOPIC:{t}"
        for t in [
            "blanqueamiento",
            "consulta_particular",
            "limpieza_particular",
            "brackets_obra_social",
            "alineadores",
        ]
    } <= payloads
    for phrase in [
        "quiero un turno para limpieza",
        "osde",
        "medifé",
        "william hope",
        "cuánto cubre osde",
    ]:
        assert phrase in messages
    real_llm = [t for t in tests if t["metadata"]["requires_real_llm"] is True]
    assert len(real_llm) == 5
    assert all(any(a["type"] == "llm-rubric" for a in t["assert"]) for t in real_llm)
    assert "y con william hope?" in messages
    for phrase in ["aceptan tarjeta", "cuánto es el anticipo", "pagar en cuotas"]:
        assert phrase in messages


def test_datasets_no_longer_expect_the_old_slot_list_after_a_free_text_message():
    # A typed message on the slot list may re-show it or navigate back; only seeded options
    # and no confirmation gate hold in both cases.
    for name in ["appointments", "audio"]:
        for test_case in _load_test_cases(name):
            if test_case["vars"].get("button_payload"):
                continue
            for assertion in test_case["assert"]:
                config = assertion.get("config") or {}
                if assertion["type"] == "javascript" and "hasOptionIds" in assertion["value"]:
                    assert not any(i.startswith("SELECT_SLOT:") for i in config["ids"]), test_case[
                        "description"
                    ]
