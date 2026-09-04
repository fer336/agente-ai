from dataclasses import dataclass


@dataclass
class Treatment:
    """Minimal treatment-plan shell, sized to type gateway Protocol signatures.

    Deliberately excludes convenio/dentista/sucursal detail present in
    Dentalink's raw `/v1/pacientes/{id}/tratamientos` response — only what a
    patient-facing WhatsApp reply needs (PRD-less, this session's own
    brief): whether it's finished, and the outstanding balance.
    """

    id: str
    patient_id: str
    name: str
    is_finished: bool
    total: float
    paid: float
    debt: float
