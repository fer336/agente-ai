from dataclasses import dataclass
from datetime import datetime

#: Single logical row — there is no per-conversation or per-tenant config
#: yet, so `RuntimeConfigRepository.get()`/`.save()` always address this
#: one id.
RUNTIME_AGENT_CONFIG_ID = "default"


@dataclass
class RuntimeAgentConfig:
    """Admin-editable agent behavior, read live at call time instead of
    being frozen into a DI singleton at process start (this session's own
    brief, no PRD.md section number) — see
    `app.application.config.runtime_config_service.RuntimeConfigService`
    for why a DB row alone isn't enough to make this "runtime".
    """

    id: str
    model: str
    temperature: float
    debounce_seconds: int
    classify_intent_prompt: str
    extract_information_prompt: str
    generate_response_prompt: str
    updated_at: datetime
    updated_by: str
