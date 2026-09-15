import pytest

from app.domain.value_objects.list_message import ListMessage, ListRow


def test_list_message_accepts_a_button_label_at_the_20_char_cap():
    # Meta's real, live-confirmed limit — exactly 20 chars must still work.
    message = ListMessage(button_label="A" * 20, rows=[ListRow(id="r1", title="Row")])

    assert message.button_label == "A" * 20


def test_list_message_rejects_a_button_label_over_the_20_char_cap():
    # Live incident: WhatsApp silently rejected an outbound list whose
    # button_label was 22 chars ("Elegí una especialidad") with
    # `[131009] Button label is too long. Max length is 20` — YCloud still
    # answered our send call with 200 OK, so nothing in our own logs
    # showed it. This must fail loudly at construction instead.
    with pytest.raises(ValueError, match="button_label exceeds"):
        ListMessage(button_label="A" * 21, rows=[ListRow(id="r1", title="Row")])
