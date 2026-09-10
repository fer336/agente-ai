"""Unit tests for the paginated WhatsApp list-message helper."""

import pytest

from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.domain.value_objects.paginated_list import (
    MAX_ROWS,
    PAGE_SIZE,
    TITLE_MAX_CHARS,
    paginate_rows,
    professional_emoji,
    professional_rows,
    specialties_list_message,
    specialty_emoji,
    specialty_rows,
    professionals_list_message,
    truncate_title,
)
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty


def _specialty(i: int) -> Specialty:
    return Specialty(id=f"spec-{i}", name=f"Especialidad {i}")


def _professional(i: int) -> Professional:
    return Professional(id=f"prof-{i}", full_name=f"Profesional {i}", specialty_id="spec-1")


class TestTruncateTitle:
    def test_short_titles_pass_through(self):
        assert truncate_title("Ortodoncia") == "Ortodoncia"

    def test_titles_over_the_whatsapp_cap_are_truncated(self):
        assert len(truncate_title("x" * 60)) <= TITLE_MAX_CHARS

    @pytest.mark.parametrize("emoji", ["🦷", "🦷✨", "👨‍⚕️"])
    def test_emoji_counted_by_characters_not_code_points(self, emoji):
        # Multi-code-point emoji (ZWJ sequences, flags-style pairs) must not
        # silently eat into the visible budget twice.
        title = f"{emoji} Ortodoncia"
        assert len(truncate_title(title)) <= TITLE_MAX_CHARS


class TestSpecialtyEmoji:
    @pytest.mark.parametrize(
        ("name", "emoji"),
        [
            ("Ortodoncia", "🦷"),
            ("Ortodoncia infantil", "😁"),
            ("Estética dental", "✨"),
            ("Endodoncia", "🔧"),
            ("Odontopediatría", "👶"),
            ("Bruxismo", "🌙"),
            ("Rehabilitación", "🛠"),
            ("Implantología", "🦷"),
            ("Cirugía", "🫁"),
            ("Limpieza", "🪥"),
            ("Algo desconocido", "🦷"),
        ],
    )
    def test_maps_names_to_identifying_emojis(self, name, emoji):
        assert specialty_emoji(name) == emoji

    def test_emoji_never_leaks_into_the_row_id(self):
        row = specialty_rows([_specialty(1)])[0]
        assert row.id == f"{SPECIALTY_PAYLOAD_PREFIX}spec-1"


class TestProfessionalEmoji:
    def test_female_first_name_gets_the_woman_emoji(self):
        assert professional_emoji("Dra. Laura Pérez") == "👩‍⚕️"

    def test_male_first_name_gets_the_man_emoji(self):
        assert professional_emoji("Dr. Carlos Adahenao") == "👨‍⚕️"

    def test_bare_names_work_too(self):
        assert professional_emoji("Camila Carasatorre") == "👩‍⚕️"
        assert professional_emoji("Juan Perez") == "👨‍⚕️"


class TestPaginateRows:
    def test_ten_items_fit_in_a_single_list_without_ver_mas(self):
        rows = [pytest.importorskip("app.domain.value_objects.list_message") and None]  # noqa: F841
        from app.domain.value_objects.list_message import ListRow

        items = [ListRow(id=f"r{i}", title=f"Row {i}") for i in range(10)]
        rendered = paginate_rows(items, page=0, include_back=False)
        assert len(rendered) == MAX_ROWS
        assert all(r.id != LIST_MORE_PAYLOAD for r in rendered)

    def test_eleven_items_show_nine_plus_ver_mas(self):
        from app.domain.value_objects.list_message import ListRow

        items = [ListRow(id=f"r{i}", title=f"Row {i}") for i in range(11)]
        rendered = paginate_rows(items, page=0, include_back=False)
        assert [r.id for r in rendered] == [f"r{i}" for i in range(9)] + [LIST_MORE_PAYLOAD]

    def test_twenty_items_page_flow(self):
        from app.domain.value_objects.list_message import ListRow

        items = [ListRow(id=f"r{i}", title=f"Row {i}") for i in range(20)]
        page0 = paginate_rows(items, page=0, include_back=False)
        page1 = paginate_rows(items, page=1, include_back=False)
        page2 = paginate_rows(items, page=2, include_back=True)
        assert [r.id for r in page0] == [f"r{i}" for i in range(9)] + [LIST_MORE_PAYLOAD]
        assert [r.id for r in page1] == [f"r{i}" for i in range(9, 18)] + [LIST_MORE_PAYLOAD]
        # Last page: the 2 remaining items fit, so the list ends with
        # 'Volver atrás' instead of 'Ver más'.
        assert [r.id for r in page2] == ["r18", "r19", LIST_BACK_PAYLOAD]

    def test_single_page_list_includes_volver_atras_when_asked(self):
        from app.domain.value_objects.list_message import ListRow

        items = [ListRow(id="r0", title="Row 0")]
        rendered = paginate_rows(items, page=0, include_back=True)
        assert [r.id for r in rendered] == ["r0", LIST_BACK_PAYLOAD]

    def test_ver_mas_rows_carry_the_navigation_title(self):
        from app.domain.value_objects.list_message import ListRow

        items = [ListRow(id=f"r{i}", title=f"Row {i}") for i in range(PAGE_SIZE + 2)]
        rendered = paginate_rows(items, page=0, include_back=False)
        assert rendered[-1].title == "Ver más"


class TestListMessages:
    def test_specialties_list_message_rows_and_labels(self):
        message = specialties_list_message(
            [_specialty(1), _specialty(2)], page=0, include_back=True
        )
        assert message.button_label
        assert [r.id for r in message.rows] == [
            f"{SPECIALTY_PAYLOAD_PREFIX}spec-1",
            f"{SPECIALTY_PAYLOAD_PREFIX}spec-2",
            LIST_BACK_PAYLOAD,
        ]
        assert message.rows[0].title.startswith("🦷 ")

    def test_professionals_list_message_rows(self):
        message = professionals_list_message(
            [_professional(1)], page=0, include_back=True
        )
        assert message.rows[0].id == "PROFESSIONAL:prof-1"
        assert message.rows[0].title.startswith(("👨‍⚕️ ", "👩‍⚕️ "))
        assert message.rows[-1].id == LIST_BACK_PAYLOAD

    def test_professional_rows_paginate_the_same_way(self):
        professionals = [_professional(i) for i in range(11)]
        rows = professional_rows(professionals, page=0, include_back=False)
        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1].id == LIST_MORE_PAYLOAD

    def test_row_titles_are_always_within_the_whatsapp_cap(self):
        long_name = Specialty(id="spec-x", name="Ortodoncia infantil avanzada premium deluxe")
        rows = specialty_rows([long_name])
        assert len(rows[0].title) <= TITLE_MAX_CHARS
