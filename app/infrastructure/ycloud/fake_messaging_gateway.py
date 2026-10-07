from app.domain.repositories.gateways import TemplateMessage
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.phone_number import PhoneNumber


class FakeYCloudMessagingGateway:
    """In-memory fake implementing `MessagingGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.sent_templates: list[tuple[PhoneNumber, TemplateMessage]] = []
        self.sent_messages: list[tuple[PhoneNumber, str]] = []
        self.sent_buttons: list[tuple[PhoneNumber, str, list[InteractiveButton], str | None]] = []
        self.sent_flows: list[tuple[PhoneNumber, str, FlowRequest]] = []
        self.sent_locations: list[tuple[PhoneNumber, LocationRequest]] = []
        self.sent_lists: list[tuple[PhoneNumber, str, ListMessage]] = []
        #: Chronological `(kind, index in its own collection)` of every send, so a
        #: consumer can tell which message went out last across the collections.
        self.sent_log: list[tuple[str, int]] = []
        self.contact_phones: dict[str, PhoneNumber] = {}
        self.typing_indicators_sent: list[str] = []
        self._next_id = 1

    async def send_template(self, to: PhoneNumber, template: TemplateMessage) -> str:
        self.sent_templates.append((to, template))
        self.sent_log.append(("template", len(self.sent_templates) - 1))
        return self._next_external_id()

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        self.sent_messages.append((to, text))
        self.sent_log.append(("text", len(self.sent_messages) - 1))
        return self._next_external_id()

    async def send_buttons(
        self,
        to: PhoneNumber,
        text: str,
        buttons: list[InteractiveButton],
        image_url: str | None = None,
    ) -> str:
        self.sent_buttons.append((to, text, buttons, image_url))
        self.sent_log.append(("buttons", len(self.sent_buttons) - 1))
        return self._next_external_id()

    async def send_flow(self, to: PhoneNumber, text: str, flow: FlowRequest) -> str:
        self.sent_flows.append((to, text, flow))
        self.sent_log.append(("flow", len(self.sent_flows) - 1))
        return self._next_external_id()

    async def send_location(self, to: PhoneNumber, location: LocationRequest) -> str:
        self.sent_locations.append((to, location))
        self.sent_log.append(("location", len(self.sent_locations) - 1))
        return self._next_external_id()

    async def send_list(self, to: PhoneNumber, text: str, list_message: ListMessage) -> str:
        self.sent_lists.append((to, text, list_message))
        self.sent_log.append(("list", len(self.sent_lists) - 1))
        return self._next_external_id()

    async def get_contact_phone(self, ycloud_contact_id: str) -> PhoneNumber | None:
        return self.contact_phones.get(ycloud_contact_id)

    async def send_typing_indicator(self, wamid: str) -> None:
        self.typing_indicators_sent.append(wamid)

    def _next_external_id(self) -> str:
        external_id = f"fake-msg-{self._next_id}"
        self._next_id += 1
        return external_id
