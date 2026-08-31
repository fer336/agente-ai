from dataclasses import dataclass
from datetime import datetime

#: `admin_users.role` — PRD.md §74.3's documented minimum roles for the
#: admin panel. `ADMIN_TECHNICAL` is the only role allowed to mutate
#: anything (e.g. resolve an error) or view restricted technical config;
#: `ADMIN_CLINIC` and `READ_ONLY` are both view-only over clinical data,
#: `ADMIN_CLINIC` additionally excluded from technical config (PRD.md §75.3).
ADMIN_TECHNICAL = "ADMIN_TECHNICAL"
ADMIN_CLINIC = "ADMIN_CLINIC"
READ_ONLY = "READ_ONLY"

ROLES = frozenset({ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY})


@dataclass
class AdminUser:
    """One admin-panel account (PRD.md §44, §74.3).

    `password_hash` is never the plaintext password — see
    `app.infrastructure.auth.password_hashing` for how it is produced/
    verified. `is_active` lets an account be disabled without deleting its
    row (audit trail, §74.3's "auditoría de accesos").
    """

    id: str
    username: str
    password_hash: str
    role: str
    is_active: bool
    created_at: datetime
