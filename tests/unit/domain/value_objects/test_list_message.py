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


def test_list_message_accepts_the_10_row_cap():
    rows = [ListRow(id=f"r{i}", title="Row") for i in range(10)]

    assert len(ListMessage(button_label="Opciones", rows=rows).rows) == 10


def test_list_message_rejects_more_than_10_rows():
    # WhatsApp rejects a list over 10 rows on its own side, so it must fail at construction.
    rows = [ListRow(id=f"r{i}", title="Row") for i in range(11)]

    with pytest.raises(ValueError, match="rows exceed"):
        ListMessage(button_label="Opciones", rows=rows)
