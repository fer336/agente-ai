from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationAdReferral:
    """The Click-to-WhatsApp ad a conversation started from.

    Meta attaches a `referral` to the first message of a lead that clicked a
    Facebook/Instagram ad; `source_id` is the ad id. `raw` keeps a bounded copy
    of the original object so the real payload shape (and fields we do not model
    yet) are never lost. A conversation holds one row per distinct `source_id`.
    """

    id: str
    conversation_id: str
    contact_id: str
    source_id: str | None
    source_type: str | None
    source_url: str | None
    headline: str | None
    ctwa_clid: str | None
    first_seen_at: datetime
    message_external_id: str | None
    raw: dict[str, object] = field(default_factory=dict)
