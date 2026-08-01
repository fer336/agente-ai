from dataclasses import dataclass


@dataclass
class ToolExecution:
    """Minimal tool execution shell, sized to type gateway Protocol signatures."""

    id: str
    agent_run_id: str
    tool_name: str
    arguments: dict[str, object]
    result: dict[str, object] | None
    status: str
