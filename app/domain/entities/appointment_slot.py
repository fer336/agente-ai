from dataclasses import dataclass

from app.domain.value_objects.date_time_range import DateTimeRange


@dataclass
class AppointmentSlot:
    """Minimal appointment slot shell, sized to type gateway Protocol signatures."""

    id: str
    professional_id: str
    specialty_id: str
    time_range: DateTimeRange
