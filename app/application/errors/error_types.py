"""Error type catalog (PRD.md §43) and their `retryable` defaults.

§43.2's own literal list (`dentalink_timeout`, `dentalink_auth_error`,
`dentalink_invalid_response`, `ycloud_error`, `openai_timeout`) is narrower
than the tokens §46's severity examples actually use
(`ycloud_auth_error`, `ycloud_webhook_failure`, `ycloud_send_failure`) — the
same document distinguishes them as meaningfully different situations (an
auth failure needs a human NOW; a single send failure might just retry).
This catalog follows §46's more specific tokens, treating `ycloud_error`
as the catch-all for anything not covered by the three more specific ones.
"""

# 43.1 Business Errors — not necessarily a system failure.
PATIENT_NOT_FOUND = "patient_not_found"
APPOINTMENT_NOT_FOUND = "appointment_not_found"
APPOINTMENT_SLOT_TAKEN = "appointment_slot_taken"
AGREEMENT_NOT_FOUND = "agreement_not_found"

# 43.2 Integration Errors.
DENTALINK_TIMEOUT = "dentalink_timeout"
DENTALINK_AUTH_ERROR = "dentalink_auth_error"
DENTALINK_INVALID_RESPONSE = "dentalink_invalid_response"
YCLOUD_ERROR = "ycloud_error"
YCLOUD_AUTH_ERROR = "ycloud_auth_error"
YCLOUD_SEND_FAILURE = "ycloud_send_failure"
YCLOUD_WEBHOOK_FAILURE = "ycloud_webhook_failure"
OPENAI_TIMEOUT = "openai_timeout"

# 43.3 System Errors.
DATABASE_ERROR = "database_error"
REDIS_ERROR = "redis_error"
UNEXPECTED_EXCEPTION = "unexpected_exception"

# 43.4 Agent Errors.
INVALID_LLM_OUTPUT = "invalid_llm_output"
INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
UNKNOWN_INTENT = "unknown_intent"
GRAPH_STATE_ERROR = "graph_state_error"

#: PRD.md §17's "el sistema deberá impedir operaciones duplicadas" spirit
#: applied to alerting: an integration hiccup is usually worth a retry: a
#: business fact (no such patient) or a permanent auth/state problem is not.
_RETRYABLE_ERROR_TYPES = frozenset(
    {
        DENTALINK_TIMEOUT,
        DENTALINK_INVALID_RESPONSE,
        YCLOUD_ERROR,
        YCLOUD_SEND_FAILURE,
        OPENAI_TIMEOUT,
        REDIS_ERROR,
    }
)


def is_retryable(error_type: str) -> bool:
    return error_type in _RETRYABLE_ERROR_TYPES
