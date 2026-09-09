"""Canonical principal WhatsApp welcome menu shared by every entry point."""

from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_LOCATION_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
)

WELCOME_TEXT = (
    "Hola! 👋 Bienvenido/a a *Smiling Pilar* 🦷\n"
    "Centro Odontológico Integral\n\n"
    "🕐 Horario de atención: lunes a viernes de *10:00* a *18:00*\n\n"
    "📸 Mirá nuestros tratamientos en Instagram: instagram.com/smiling.pilar\n\n"
    "¿En qué te puedo ayudar hoy?"
)

WELCOME_LIST = ListMessage(
    button_label="Elegí una opción",
    rows=[
        ListRow(id=OPERATION_CREATE_PAYLOAD, title="📅 Agendar una cita"),
        ListRow(id=OPERATION_RESCHEDULE_PAYLOAD, title="🔄 Reprogramar mi cita"),
        ListRow(id=OPERATION_CANCEL_PAYLOAD, title="❌ Cancelar mi cita"),
        ListRow(id=MENU_SPECIALTIES_PAYLOAD, title="🦷 Tratamientos y precios"),
        ListRow(id=MENU_LOCATION_PAYLOAD, title="📍 Cómo llegar"),
        ListRow(id=MENU_ADMIN_PAYLOAD, title="💬 Hablar con un asesor"),
        ListRow(id=OPERATION_VIEW_PAYLOAD, title="📋 Ver mi cita"),
    ],
)
