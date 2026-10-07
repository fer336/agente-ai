"""Central, fail-closed recipient policy for appointment reminders."""

from dataclasses import dataclass, field
from typing import Literal

from app.domain.value_objects.phone_number import PhoneNumber

ReminderRolloutMode = Literal["allowlist", "all"]


@dataclass(frozen=True)
class ReminderRecipientPolicy:
    """Immutable rollout policy applied before reminder scheduling and delivery."""

    mode: ReminderRolloutMode = "allowlist"
    allowlist: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized: set[str] = set()
        for phone in self.allowlist:
            normalized.add(str(PhoneNumber(phone.strip())))
        object.__setattr__(self, "allowlist", frozenset(normalized))

    def can_run(self, *, enabled: bool) -> bool:
        """Whether a reminder run may start without contacting Dentalink."""
        return enabled and (
            self.mode == "all" or (self.mode == "allowlist" and bool(self.allowlist))
        )

    def allows(self, phone: PhoneNumber | str) -> bool:
        """Return whether a valid, normalized recipient is in this rollout."""
        try:
            normalized = str(PhoneNumber(str(phone)))
        except (TypeError, ValueError):
            return False
        return self.mode == "all" or (self.mode == "allowlist" and normalized in self.allowlist)
