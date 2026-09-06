import json

#: Dentalink's documented filter operators. Kept narrow on purpose — this
#: codebase only ever needs equality today, and a caller that needs more
#: should widen this deliberately rather than by accident.
DEFAULT_ALLOWED_OPERATORS = frozenset({"eq", "neq", "lk"})


def build_q_param(
    filters: dict[str, tuple[str, object]],
    *,
    allowed_fields: frozenset[str],
    allowed_operators: frozenset[str] = DEFAULT_ALLOWED_OPERATORS,
) -> dict[str, str]:
    """Builds Dentalink's `?q={"campo":{"operador":"valor"}}` filter param.

    This is Dentalink's real, documented convention across `/pacientes`,
    `/dentistas`, `/especialidades` and `/v5/agendas` (confirmed against
    https://api.dentalink.healthatom.com/docs/) — NOT the bracket-notation
    `filtro[campo][operador]=valor` form this codebase used to guess at for
    `/v5/agendas`, which silently did not filter at all.

    `allowed_fields` is per-endpoint and caller-supplied on purpose: one
    Dentalink resource's columns are not another's, so sharing a single
    allow-list across resources would quietly permit nonsense filters.

    Guardrail against filter/query injection: a caller-controlled value
    (e.g. a patient's own free-text name) can only ever become a JSON
    *value*, never a JSON *key* or operator — the query is always built as
    a Python dict and serialized with `json.dumps`, never by
    string-interpolating into a hand-built query string.
    """
    query: dict[str, dict[str, object]] = {}
    for field, (operator, value) in filters.items():
        if field not in allowed_fields:
            raise ValueError(f"Filtering by {field!r} is not allowed")
        if operator not in allowed_operators:
            raise ValueError(f"Operator {operator!r} is not allowed")
        query[field] = {operator: value}
    return {"q": json.dumps(query, separators=(",", ":"))}
