from dataclasses import dataclass
from datetime import datetime

#: `admin_audit_log.action` — the operations PRD.md §74.3 requires auditing
#: ("auditoría de accesos y cambios sensibles"). Login attempts are audited
#: even when they fail (no `admin_user_id` yet at that point).
LOGIN_SUCCESS = "login_success"
LOGIN_FAILURE = "login_failure"
VIEW_CONVERSATION = "view_conversation"
VIEW_ERROR = "view_error"
RESOLVE_ERROR = "resolve_error"


@dataclass
class AdminAuditLogEntry:
    """One audited admin-panel access or change (PRD.md §74.3).

    `admin_user_id`/`username` are both stored (not just the id) so a login
    failure — which has no valid `admin_user_id` — still records which
    username was attempted, without ever storing the password itself.
    """

    id: str
    admin_user_id: str | None
    username: str
    action: str
    resource_type: str | None
    resource_id: str | None
    success: bool
    created_at: datetime
