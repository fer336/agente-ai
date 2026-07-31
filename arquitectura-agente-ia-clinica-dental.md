# Arquitectura — Agente de IA para una clínica dental

Documento base para `docs/architecture.md`.

Este proyecto está diseñado exclusivamente para una clínica dental específica. No se implementará como plataforma SaaS ni como sistema multi-tenant.

La aplicación tendrá una única configuración de WhatsApp, Dentalink, Chatwoot, base de conocimiento y proveedor de inteligencia artificial.

# 1. Objetivo de la arquitectura

Construir un agente de inteligencia artificial capaz de atender consultas administrativas mediante WhatsApp y gestionar turnos en Dentalink de forma segura, controlada y auditable.

El agente podrá:

- Responder preguntas frecuentes.
- Informar horarios, ubicación, tratamientos
- Consultar disponibilidad.
- Solicitar turnos.
- Crear turnos.
- Reprogramar turnos.
- Cancelar turnos.
- Confirmar operaciones antes de ejecutarlas.
- Derivar conversaciones a una persona.
- Registrar conversaciones y acciones.

El agente no realizará diagnósticos médicos ni dará indicaciones clínicas fuera del contenido aprobado por la clínica.

# 2. Estilo arquitectónico

Se utilizará una:

> Arquitectura hexagonal dentro de un monolito modular.

La aplicación estará desarrollada principalmente en Python y FastAPI.

Aunque se ejecute mediante diferentes procesos, todo formará parte del mismo repositorio y de la misma aplicación:

- API.
- Agente LangGraph.
- Workers.
- Scheduler.
- Integraciones.
- Casos de uso.
- Dominio.
- Persistencia.

No se utilizarán microservicios durante el MVP.

## Motivos

- El sistema pertenece a una sola clínica.
- El equipo de desarrollo es reducido.
- La lógica de agenda necesita consistencia.
- Un único despliegue simplifica mantenimiento y monitoreo.
- No existe una necesidad real de escalado distribuido.
- La separación interna permite dividir servicios en el futuro si fuera necesario.

# 3. Stack tecnológico

## Aplicación

- Python.
- FastAPI.
- LangGraph.
- Pydantic.
- SQLAlchemy asíncrono.
- Alembic.

## Persistencia

- PostgreSQL.
- Redis.

## Integraciones

- Dentalink.
- WhatsApp Business Cloud API o proveedor autorizado.
- Chatwoot.
- Proveedor de modelos de lenguaje.
- n8n para procesos secundarios.

## Infraestructura

- Docker.
- Docker Compose.
- Traefik o Nginx.
- GitHub Actions.
- Sentry.
- Logs estructurados en JSON.

# 4. Arquitectura general

    Paciente
       │
       ▼
    WhatsApp
       │
       ▼
    Webhook FastAPI
       │
       ├── Validación de firma
       ├── Idempotencia del mensaje
       └── Persistencia inicial
       │
       ▼
    Redis
       ├── Debounce
       ├── Lock por conversación
       ├── Rate limiting
       └── Caché temporal
       │
       ▼
    Servicio de conversación
       │
       ▼
    LangGraph
       │
       ├── Consulta informativa
       ├── Gestión de turnos
       ├── Confirmación
       ├── Derivación humana
       └── Respuesta segura
       │
       ▼
    Capa de aplicación
       │
       ├── Buscar disponibilidad
       ├── Crear turno
       ├── Reprogramar turno
       ├── Cancelar turno
       ├── Consultar información
       └── Derivar conversación
       │
       ▼
    Adaptadores
       ├── Dentalink
       ├── Chatwoot
       ├── WhatsApp
       ├── PostgreSQL
       ├── Redis
       └── Proveedor LLM

# 5. Componentes principales

## 5.1 API FastAPI

FastAPI será el punto de entrada principal del sistema.

Responsabilidades:

- Recibir webhooks de WhatsApp.
- Validar firmas.
- Detectar mensajes duplicados.
- Registrar mensajes.
- Consultar el estado de la conversación.
- Enviar mensajes al agente.
- Exponer endpoints administrativos.
- Exponer endpoints de salud.
- Recibir eventos de Chatwoot.
- Recibir callbacks de integraciones.
- Permitir que n8n invoque procesos autorizados.

FastAPI no contendrá lógica de negocio directamente dentro de los endpoints.

Los endpoints deberán invocar casos de uso de la capa `application`.

## 5.2 Agente LangGraph

LangGraph administrará el flujo conversacional.

Su responsabilidad será:

- Interpretar el mensaje.
- Identificar la intención.
- Detectar datos faltantes.
- Decidir el siguiente paso.
- Solicitar herramientas.
- Esperar confirmaciones.
- Derivar a una persona.
- Generar una respuesta adecuada.

LangGraph no deberá:

- Llamar directamente a Dentalink.
- Llamar directamente a PostgreSQL.
- Ejecutar SQL.
- Gestionar credenciales.
- Confirmar una acción sin validar el resultado real.
- Crear turnos mediante texto libre generado por el modelo.

El agente utilizará herramientas que invoquen casos de uso.

Ejemplo:

    LangGraph
       ↓
    SearchAvailabilityTool
       ↓
    SearchAvailabilityUseCase
       ↓
    AppointmentGateway
       ↓
    DentalinkGateway

## 5.3 Capa de aplicación

La capa `application` contendrá los casos de uso del sistema.

Ejemplos:

- `SearchAvailabilityUseCase`
- `CreateAppointmentUseCase`
- `RescheduleAppointmentUseCase`
- `CancelAppointmentUseCase`
- `ConfirmPendingActionUseCase`
- `RequestHumanHandoffUseCase`
- `SendMessageUseCase`
- `GetApprovedContentUseCase`
- `IdentifyPatientUseCase`

Esta capa:

- Coordina reglas de negocio.
- Usa interfaces del dominio.
- Controla transacciones.
- Registra auditoría.
- Genera eventos.
- Valida permisos.
- Aplica idempotencia.

No deberá conocer detalles internos de Dentalink, WhatsApp o Chatwoot.

## 5.4 Dominio

La capa `domain` contendrá lógica pura.

Entidades iniciales:

- `Patient`
- `Contact`
- `Conversation`
- `Message`
- `Appointment`
- `AppointmentSlot`
- `PendingAction`
- `ToolExecution`
- `HumanHandoff`
- `ApprovedContent`
- `OutboxEvent`

Value objects:

- `PhoneNumber`
- `PatientId`
- `ConversationId`
- `ExternalMessageId`
- `AppointmentId`
- `IdempotencyKey`
- `DateTimeRange`
- `ConfirmationToken`

Interfaces:

- `AppointmentGateway`
- `ConversationRepository`
- `MessageRepository`
- `PendingActionRepository`
- `KnowledgeRepository`
- `HumanHandoffGateway`
- `MessagingGateway`
- `LLMProvider`
- `OutboxRepository`

El dominio no dependerá de:

- FastAPI.
- SQLAlchemy.
- Redis.
- LangGraph.
- Dentalink.
- Chatwoot.
- WhatsApp.
- SDK de inteligencia artificial.

## 5.5 Adaptador Dentalink

Dentalink estará encapsulado detrás de `AppointmentGateway`.

Interfaz conceptual:

    class AppointmentGateway(Protocol):
        async def search_availability(
            self,
            specialty_id: str | None,
            professional_id: str | None,
            date_range: DateTimeRange,
        ) -> list[AppointmentSlot]:
            ...

        async def create_appointment(
            self,
            patient: Patient,
            slot: AppointmentSlot,
            idempotency_key: str,
        ) -> Appointment:
            ...

        async def reschedule_appointment(
            self,
            appointment_id: str,
            new_slot: AppointmentSlot,
            idempotency_key: str,
        ) -> Appointment:
            ...

        async def cancel_appointment(
            self,
            appointment_id: str,
            idempotency_key: str,
        ) -> None:
            ...

Implementaciones:

    infrastructure/dentalink/
    ├── dentalink_client.py
    ├── dentalink_gateway.py
    ├── fake_dentalink_gateway.py
    ├── schemas.py
    ├── mapper.py
    └── exceptions.py

El agente nunca deberá conocer `DentalinkClient`.

Durante el desarrollo se utilizará `FakeDentalinkGateway`.

## 5.6 Chatwoot

Chatwoot será la interfaz de atención humana.

Funciones:

- Mostrar conversaciones.
- Permitir intervención humana.
- Asignar conversaciones.
- Agregar etiquetas.
- Agregar notas internas.
- Pausar el agente.
- Reactivar el agente.
- Registrar derivaciones.

El estado de control humano deberá guardarse también en PostgreSQL.

Ejemplo:

    conversation_mode:
    - agent
    - human
    - paused
    - closed

Cuando el modo sea `human`, LangGraph no responderá automáticamente.

La reactivación deberá ser explícita.

## 5.7 Redis

Redis se usará únicamente para información temporal.

Usos:

- Debounce.
- Locks distribuidos.
- Rate limiting.
- Caché.
- Cola de tareas.
- Coordinación de workers.
- Claves temporales de idempotencia.
- Estado de procesamiento corto.

Redis no será fuente de verdad.

Una caída de Redis no deberá eliminar:

- Conversaciones.
- Mensajes.
- Acciones pendientes.
- Confirmaciones.
- Turnos.
- Auditorías.
- Estado de atención humana.

## 5.8 PostgreSQL

PostgreSQL será la fuente de verdad.

Tablas iniciales:

    patients
    contacts
    conversations
    messages
    conversation_states
    appointments
    appointment_actions
    pending_actions
    tool_executions
    human_handoffs
    approved_contents
    prompt_versions
    outbox_events
    agent_runs
    errors
    system_settings

No se utilizará `clinic_id`, porque el sistema pertenece a una sola clínica.

# 6. Flujo de recepción de mensajes

    1. WhatsApp envía el webhook.
    2. FastAPI valida la firma.
    3. Se obtiene el identificador externo del mensaje.
    4. PostgreSQL verifica si el mensaje ya existe.
    5. Si existe, se ignora.
    6. Si es nuevo, se registra.
    7. Redis aplica debounce.
    8. Los mensajes consecutivos se agrupan.
    9. Se obtiene un lock para la conversación.
    10. Se verifica si un humano controla la conversación.
    11. Si hay atención humana, no responde el agente.
    12. Si el agente está activo, se carga el estado.
    13. LangGraph procesa el mensaje.
    14. El agente utiliza herramientas autorizadas.
    15. Se guarda el resultado.
    16. Se crea un evento de salida.
    17. El worker envía la respuesta.
    18. Se registra el envío.
    19. Se libera el lock.

# 7. Debounce

El sistema deberá agrupar mensajes consecutivos.

Ejemplo:

    Hola
    Quería consultar
    Por una limpieza
    Para mañana

En lugar de responder cuatro veces, se procesará como:

    Hola. Quería consultar por una limpieza para mañana.

Configuración inicial:

    MESSAGE_DEBOUNCE_SECONDS=6

El rango recomendado es de 4 a 8 segundos.

Clave Redis sugerida:

    debounce:conversation:{conversation_id}

# 8. Grafo inicial de LangGraph

El grafo debe ser pequeño y comprensible.

    receive_message
           ↓
    check_human_control
           ↓
    understand_request
           ↓
    route_intent
       ┌──────┼───────────┐
       ↓      ↓           ↓
    inform appointment  handoff
              ↓
    collect_information
              ↓
    identify_patient
              ↓
    search_availability
              ↓
    present_options
              ↓
    request_confirmation
              ↓
    execute_action
              ↓
    generate_response

No todas las tareas técnicas deberán transformarse en nodos.

No hace falta crear nodos específicos para:

- Guardar logs.
- Persistir mensajes.
- Capturar excepciones.
- Generar métricas.
- Abrir conexiones.
- Ejecutar middleware.

Estas operaciones deben resolverse mediante servicios y wrappers.

# 9. Estado del agente

El estado de LangGraph contendrá únicamente información conversacional.

Ejemplo:

    class AgentState(TypedDict):
        conversation_id: str
        message_ids: list[str]
        user_message: str
        intent: str | None
        collected_data: dict[str, object]
        missing_fields: list[str]
        pending_action_id: str | None
        response_text: str | None
        requires_handoff: bool

Las acciones críticas no deberán existir únicamente dentro del estado del grafo.

Por ejemplo, una cancelación pendiente deberá persistirse en PostgreSQL.

# 10. Acciones pendientes

Antes de crear, modificar o cancelar un turno se deberá crear una acción pendiente.

Tabla sugerida:

    pending_actions
    - id
    - conversation_id
    - action_type
    - payload
    - confirmation_token
    - status
    - expires_at
    - created_at
    - confirmed_at
    - executed_at

Estados:

    pending
    confirmed
    executing
    completed
    expired
    failed
    cancelled

Tipos:

    create_appointment
    reschedule_appointment
    cancel_appointment
    update_patient

El agente deberá asociar cada respuesta afirmativa con una acción pendiente concreta.

# 11. Confirmación explícita

Ejemplo:

    Tengo disponible un turno para limpieza con la Dra. Pérez
    el martes 4 de agosto a las 15:30.

    ¿Confirmás que querés reservarlo?

Respuestas aceptadas:

- Sí.
- Confirmo.
- Dale, confirmalo.
- Reservalo.
- Sí, ese turno.

Respuestas ambiguas:

- Puede ser.
- Después veo.
- Quizás.
- Bueno.
- El otro.
- Hacé lo que te parezca.

Las respuestas ambiguas no deberán ejecutar acciones.

# 12. Idempotencia

La idempotencia tendrá dos niveles.

## 12.1 Mensajes

Cada mensaje tendrá un `external_message_id` único.

    messages.external_message_id UNIQUE

## 12.2 Operaciones de agenda

Cada acción tendrá una clave persistente.

    appointment_actions.idempotency_key UNIQUE

Ejemplo:

    create:conversation-123:pending-action-456

Redis podrá ayudar temporalmente, pero PostgreSQL deberá garantizar que una operación no se repita aunque Redis se reinicie.

# 13. Outbox Pattern

Se utilizará una tabla `outbox_events`.

Objetivo:

Evitar repetir una operación de negocio cuando solamente falló el envío del mensaje.

Ejemplo:

    1. Dentalink crea el turno.
    2. PostgreSQL registra el turno.
    3. PostgreSQL crea appointment.created.
    4. El worker intenta enviar WhatsApp.
    5. WhatsApp falla.
    6. El evento queda pendiente.
    7. El worker reintenta el envío.
    8. No se vuelve a crear el turno.

Tabla:

    outbox_events
    - id
    - event_type
    - aggregate_type
    - aggregate_id
    - payload
    - status
    - attempts
    - available_at
    - created_at
    - processed_at
    - last_error

Eventos iniciales:

    appointment.created
    appointment.rescheduled
    appointment.cancelled
    message.reply_requested
    human_handoff.requested
    reminder.requested

# 14. Workers

La aplicación tendrá al menos un proceso worker separado.

El worker podrá implementarse con:

- ARQ.
- Dramatiq.
- Celery.

Para este proyecto se recomienda comenzar con ARQ o Dramatiq por su menor complejidad.

Responsabilidades:

- Procesar outbox.
- Enviar mensajes.
- Reintentar integraciones.
- Ejecutar recordatorios.
- Sincronizar datos secundarios.
- Procesar tareas demoradas.
- Generar reportes.
- Enviar alertas.

No se utilizará `BackgroundTasks` de FastAPI para operaciones críticas.

# 15. Scheduler

Las tareas programadas podrán ejecutarse mediante:

- Worker con scheduler.
- n8n.
- Cron del servidor.

n8n se utilizará solamente para tareas periféricas.

Ejemplos:

- Recordatorios de turnos.
- Informe diario.
- Encuestas de satisfacción.
- Alertas operativas.
- Resumen de conversaciones.
- Notificaciones internas.

n8n no tendrá acceso directo a Dentalink ni a PostgreSQL.

Deberá invocar endpoints internos autorizados de FastAPI.

# 16. Base de conocimiento

La primera versión no utilizará RAG complejo.

La información estable se almacenará de forma estructurada.

Tablas sugeridas:

    treatments
    professionals
    locations
    opening_hours
    payment_methods
    insurance_providers
    prices
    frequently_asked_questions
    policies
    emergency_messages

El agente podrá buscar contenido mediante:

- Categoría.
- Intención.
- Palabras clave.
- Identificador de tratamiento.
- Identificador de profesional.

El modelo no deberá inventar:

- Precios.
- Horarios.
- Obras sociales.
- Coberturas.
- Profesionales.
- Disponibilidad.
- Políticas de cancelación.

# 17. Integración con el proveedor LLM

El proveedor deberá estar abstraído mediante una interfaz.

    class LLMProvider(Protocol):
        async def classify_intent(
            self,
            message: str,
            context: dict[str, object],
        ) -> IntentResult:
            ...

        async def extract_information(
            self,
            message: str,
            required_fields: list[str],
        ) -> ExtractionResult:
            ...

        async def generate_response(
            self,
            context: ResponseContext,
        ) -> str:
            ...

El resultado del modelo deberá validarse con Pydantic.

El modelo no podrá ejecutar herramientas mediante argumentos sin validar.

Ejemplo:

    class CreateAppointmentArguments(BaseModel):
        patient_id: str
        slot_id: str
        pending_action_id: str

# 18. Seguridad clínica

El agente será administrativo, no médico.

No podrá:

- Diagnosticar.
- Recomendar medicamentos.
- Indicar dosis.
- Interpretar estudios.
- Garantizar resultados.
- Restar importancia a síntomas.
- Inventar tratamientos.
- Revelar datos de otros pacientes.

Ante una posible urgencia:

    1. Informar que no puede realizar diagnóstico.
    2. Recomendar comunicación inmediata con la clínica.
    3. Mostrar el mensaje aprobado para urgencias.
    4. Derivar a atención humana.
    5. Registrar la derivación.

# 19. Identificación del paciente

El número de WhatsApp no deberá considerarse identidad suficiente para operaciones sensibles.

Para consultar, cancelar o reprogramar un turno se podrá solicitar:

- Nombre y apellido.
- DNI.
- Fecha de nacimiento.
- Número de teléfono registrado.
- Código de verificación.

La clínica deberá definir qué combinación de datos resulta suficiente.

Ejemplo inicial:

    nombre completo + DNI

Los datos se validarán contra Dentalink antes de mostrar información del turno.

# 20. Manejo de errores

Errores previstos:

- Dentalink no disponible.
- WhatsApp no disponible.
- Chatwoot no disponible.
- Redis no disponible.
- PostgreSQL no disponible.
- Proveedor LLM no disponible.
- Timeout.
- Error de autenticación.
- Turno ocupado durante la confirmación.
- Mensaje duplicado.
- Acción duplicada.
- Paciente no identificado.
- Respuesta inválida del modelo.
- Respuesta inválida de Dentalink.

Reglas:

- No informar éxito sin confirmación real.
- Registrar el error.
- Crear una traza.
- Mostrar un mensaje comprensible.
- Ofrecer derivación humana.
- Reintentar únicamente cuando sea seguro.
- No repetir operaciones no idempotentes.

# 21. Observabilidad

Se implementarán logs estructurados.

Campos sugeridos:

    timestamp
    level
    trace_id
    conversation_id
    message_id
    agent_run_id
    tool_name
    operation
    duration_ms
    status
    error_type

Métricas iniciales:

- Conversaciones recibidas.
- Mensajes procesados.
- Intenciones.
- Consultas resueltas.
- Turnos creados.
- Turnos reprogramados.
- Turnos cancelados.
- Derivaciones humanas.
- Errores por integración.
- Tiempo de respuesta.
- Uso del modelo.
- Consumo estimado.
- Operaciones duplicadas bloqueadas.

Sentry se utilizará para errores inesperados.

# 22. Estructura del repositorio

    clinic-ai-agent/
    ├── app/
    │   ├── main.py
    │   │
    │   ├── api/
    │   │   ├── routes/
    │   │   │   ├── whatsapp.py
    │   │   │   ├── chatwoot.py
    │   │   │   ├── admin.py
    │   │   │   └── health.py
    │   │   ├── dependencies/
    │   │   ├── middleware/
    │   │   └── schemas/
    │   │
    │   ├── agent/
    │   │   ├── graph.py
    │   │   ├── state.py
    │   │   ├── routing.py
    │   │   ├── nodes/
    │   │   │   ├── understand_request.py
    │   │   │   ├── collect_information.py
    │   │   │   ├── search_availability.py
    │   │   │   ├── request_confirmation.py
    │   │   │   ├── execute_action.py
    │   │   │   ├── generate_response.py
    │   │   │   └── handoff.py
    │   │   ├── tools/
    │   │   ├── prompts/
    │   │   └── policies/
    │   │
    │   ├── application/
    │   │   ├── appointments/
    │   │   │   ├── search_availability.py
    │   │   │   ├── create_appointment.py
    │   │   │   ├── reschedule_appointment.py
    │   │   │   └── cancel_appointment.py
    │   │   ├── conversations/
    │   │   ├── patients/
    │   │   ├── knowledge/
    │   │   ├── handoff/
    │   │   └── messaging/
    │   │
    │   ├── domain/
    │   │   ├── entities/
    │   │   ├── value_objects/
    │   │   ├── repositories/
    │   │   ├── services/
    │   │   ├── events/
    │   │   └── exceptions/
    │   │
    │   ├── infrastructure/
    │   │   ├── database/
    │   │   │   ├── models/
    │   │   │   ├── repositories/
    │   │   │   └── session.py
    │   │   ├── dentalink/
    │   │   ├── whatsapp/
    │   │   ├── chatwoot/
    │   │   ├── llm/
    │   │   ├── redis/
    │   │   ├── outbox/
    │   │   └── observability/
    │   │
    │   ├── workers/
    │   │   ├── worker.py
    │   │   ├── outbox_tasks.py
    │   │   ├── reminder_tasks.py
    │   │   └── retry_tasks.py
    │   │
    │   └── config/
    │       ├── settings.py
    │       └── logging.py
    │
    ├── migrations/
    ├── tests/
    │   ├── unit/
    │   ├── integration/
    │   ├── agent/
    │   ├── contracts/
    │   └── end_to_end/
    ├── docs/
    │   ├── architecture.md
    │   ├── api.md
    │   ├── deployment.md
    │   ├── runbook.md
    │   └── adr/
    ├── scripts/
    ├── docker/
    ├── docker-compose.yml
    ├── pyproject.toml
    ├── alembic.ini
    ├── .env.example
    └── README.md

# 23. Servicios de Docker Compose

    api
    worker
    postgres
    redis
    chatwoot
    chatwoot-worker
    traefik

Opcionales:

    n8n
    sentry
    grafana
    loki

Para el MVP no se utilizará Docker Swarm.

# 24. Variables de entorno

    APP_ENV=development
    APP_SECRET_KEY=
    LOG_LEVEL=INFO

    DATABASE_URL=postgresql+asyncpg://
    REDIS_URL=redis://redis:6379/0

    DENTALINK_API_URL=
    DENTALINK_API_KEY=
    DENTALINK_TIMEOUT_SECONDS=15

    WHATSAPP_API_URL=
    WHATSAPP_ACCESS_TOKEN=
    WHATSAPP_PHONE_NUMBER_ID=
    WHATSAPP_VERIFY_TOKEN=
    WHATSAPP_APP_SECRET=

    CHATWOOT_URL=
    CHATWOOT_API_TOKEN=
    CHATWOOT_ACCOUNT_ID=
    CHATWOOT_INBOX_ID=

    LLM_PROVIDER=
    LLM_API_KEY=
    LLM_MODEL=

    MESSAGE_DEBOUNCE_SECONDS=6
    PENDING_ACTION_EXPIRATION_MINUTES=10

    SENTRY_DSN=

# 25. Alcance del MVP

El MVP incluirá:

1. Recepción de mensajes de WhatsApp.
2. Validación de webhooks.
3. Debounce.
4. Persistencia de conversaciones.
5. Sincronización con Chatwoot.
6. Pausa del agente cuando interviene una persona.
7. Respuestas informativas aprobadas.
8. Identificación básica de intención.
9. Consulta de disponibilidad en Dentalink.
10. Creación de turnos.
11. Reprogramación.
12. Cancelación.
13. Confirmación explícita.
14. Acciones pendientes.
15. Idempotencia.
16. Auditoría.
17. Outbox.
18. Worker de reintentos.
19. Manejo seguro de errores.
20. Logs y métricas básicas.
21. Despliegue mediante Docker Compose.
22. Pruebas unitarias, de integración y end-to-end.

# 26. Fuera del MVP

No se implementará inicialmente:

- Multi-tenancy.
- Varias clínicas.
- Gestión de suscripciones.
- Facturación SaaS.
- Panel multi-cliente.
- Configuración por tenant.
- Routing por clínica.
- Microservicios.
- Kubernetes.
- Docker Swarm.
- Agente de voz.
- RAG avanzado.
- Diagnóstico médico.
- Campañas comerciales complejas.
- Múltiples agentes coordinados.
- Aplicación móvil propia.

# 27. Plan de implementación

## Etapa 0 — Fundación

- Crear repositorio.
- Configurar `pyproject.toml`.
- Configurar linting.
- Configurar tipado.
- Configurar pre-commit.
- Crear Docker Compose.
- Levantar PostgreSQL y Redis.
- Configurar CI.
- Crear `.env.example`.

## Etapa 1 — Dominio

- Crear entidades.
- Crear value objects.
- Crear interfaces.
- Crear excepciones.
- Diseñar acciones pendientes.
- Diseñar eventos de dominio.

## Etapa 2 — Persistencia

- Crear modelos SQLAlchemy.
- Crear migraciones.
- Crear repositorios.
- Crear restricciones únicas.
- Crear tabla de outbox.
- Crear tabla de auditoría.

## Etapa 3 — Adaptadores simulados

- Fake WhatsApp.
- Fake Chatwoot.
- Fake Dentalink.
- Fake LLM.
- Fixtures de prueba.

## Etapa 4 — Pipeline de mensajes

- Webhook.
- Validación.
- Idempotencia.
- Persistencia.
- Debounce.
- Locks.
- Agrupación de mensajes.

## Etapa 5 — LangGraph básico

- Estado del agente.
- Clasificación.
- Enrutamiento.
- Consulta informativa.
- Derivación humana.
- Persistencia del estado.

## Etapa 6 — Gestión de turnos

- Identificación del paciente.
- Consulta de disponibilidad.
- Selección.
- Acción pendiente.
- Confirmación.
- Creación.
- Reprogramación.
- Cancelación.

## Etapa 7 — Auditoría y outbox

- Trazas.
- Registro de herramientas.
- Eventos.
- Worker.
- Reintentos.
- Manejo de fallos.

## Etapa 8 — Pruebas completas con fakes

- Tests unitarios.
- Tests de integración.
- Tests del grafo.
- Tests end-to-end.
- Simulación de errores.
- Simulación de duplicados.

## Etapa 9 — WhatsApp real

- Credenciales.
- Webhook real.
- Validación de firma.
- Envío de mensajes.
- Manejo de plantillas.

## Etapa 10 — Chatwoot real

- Creación y sincronización de conversaciones.
- Pausa humana.
- Reactivación.
- Etiquetas.
- Notas internas.

## Etapa 11 — Dentalink real

- Cliente HTTP.
- Autenticación.
- Disponibilidad.
- Pacientes.
- Turnos.
- Reprogramación.
- Cancelación.
- Manejo de conflictos.

## Etapa 12 — Contenido de la clínica

- Tratamientos.
- Precios.
- Horarios.
- Profesionales.
- Obras sociales.
- Preguntas frecuentes.
- Políticas.
- Mensajes de urgencia.

## Etapa 13 — Piloto

- Modo observación.
- Revisión humana.
- Ajuste de prompts.
- Evaluación de intenciones.
- Medición de errores.
- Medición de derivaciones.

## Etapa 14 — Producción gradual

1. Consultas informativas.
2. Consulta de disponibilidad.
3. Creación de turnos.
4. Reprogramación.
5. Cancelación.
6. Recordatorios.

# 28. ADRs iniciales

Crear:

    0001-monolito-modular.md
    0002-arquitectura-hexagonal.md
    0003-postgresql-fuente-de-verdad.md
    0004-redis-solo-estado-temporal.md
    0005-langgraph-como-orquestador.md
    0006-outbox-para-mensajeria.md
    0007-n8n-solo-procesos-perifericos.md
    0008-confirmacion-explicita-operaciones.md

# 29. Instrucción para Claude Code

Utilizá este documento como especificación arquitectónica principal.

El sistema pertenece a una sola clínica.

No agregues:

- `tenant_id`.
- `clinic_id` en todas las tablas.
- Sistemas multi-tenant.
- Paneles para múltiples clínicas.
- Configuración dinámica por cliente.
- Microservicios.
- Kubernetes.
- Escalabilidad horizontal innecesaria.

Antes de implementar integraciones reales:

1. Creá la estructura del repositorio.
2. Definí el dominio.
3. Definí interfaces.
4. Configurá PostgreSQL y Redis.
5. Implementá adaptadores simulados.
6. Implementá el pipeline de mensajes.
7. Implementá el grafo básico.
8. Creá pruebas.
9. Implementá idempotencia.
10. Implementá outbox.
11. Recién después conectá WhatsApp, Chatwoot y Dentalink.

Priorizá:

- Seguridad.
- Simplicidad.
- Trazabilidad.
- Tipado.
- Pruebas.
- Idempotencia.
- Recuperación ante errores.
- Separación entre IA y reglas de negocio.

El modelo de lenguaje puede interpretar solicitudes, pero nunca deberá decidir por sí solo que una operación crítica fue completada.

Toda creación, reprogramación o cancelación deberá:

1. Estar asociada a una acción pendiente.
2. Requerir confirmación explícita.
3. Utilizar una clave de idempotencia.
4. Ejecutarse mediante un caso de uso.
5. Validarse contra Dentalink.
6. Registrarse en auditoría.
7. Informarse al paciente solamente después de recibir una respuesta válida.

# 30. Requerimientos técnicos del proyecto

Los siguientes paquetes conforman la base recomendada para comenzar el desarrollo. Se utilizará OpenAI como proveedor principal del modelo, manteniendo la integración abstraída para poder reemplazarla sin modificar el dominio ni los casos de uso.

## 30.1 Archivo requirements.txt

```text
# API y servidor
fastapi
uvicorn[standard]
# LangGraph y proveedor LLM
langgraph
langgraph-checkpoint-postgres
langchain-core
langchain-openai
# Configuración y validación
pydantic
pydantic-settings
# Persistencia
sqlalchemy[asyncio]
asyncpg
psycopg[binary,pool]
alembic
# Redis, workers y coordinación
redis
arq
# Integraciones HTTP y resiliencia
httpx
tenacity
# Logs y observabilidad
structlog
sentry-sdk[fastapi]
# Utilidades
python-multipart
# Desarrollo y pruebas
pytest
pytest-asyncio
pytest-cov
respx
ruff
mypy
```


## 30.2 Dependencias opcionales

- gradio: interfaz interna para probar el agente sin WhatsApp.
- langsmith: trazas y evaluación de LangGraph, con anonimización de datos sensibles.
- langchain-google-genai: proveedor alternativo con Gemini.
- tavily-python o langchain-tavily: búsqueda web controlada. No debe utilizarse para turnos, precios, pacientes ni información clínica.

## 30.3 Librerías que no se incorporan inicialmente

- langchain-community, porque agrega integraciones que no son necesarias para el MVP.
- requests, porque la aplicación será asíncrona y utilizará httpx.AsyncClient.
- RAG, bases vectoriales y embeddings, porque la primera base de conocimiento será estructurada.
- Frameworks multiagente, porque el flujo debe ser controlado, pequeño y auditable.

## 30.4 Instalación inicial

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

# 31. Elementos necesarios antes de comenzar el diseño

Antes de implementar funcionalidades reales se deben cerrar los siguientes puntos. El desarrollo puede iniciar con adaptadores simulados, pero las integraciones reales no deben programarse sin disponer de la documentación y las reglas operativas correspondientes.

## 31.1 Información funcional de la clínica

- Listado de tratamientos y especialidades.
- Listado de profesionales y horarios de atención.
- Duración de cada tipo de turno.
- Reglas para pacientes nuevos y existentes.
- Políticas de creación, cancelación y reprogramación.
- Datos necesarios para identificar a un paciente.
- Preguntas frecuentes y respuestas aprobadas.
- Precios o rangos que el agente puede comunicar.
- Obras sociales, prepagas y medios de pago.
- Mensajes aprobados para urgencias y derivación humana.
- Horario de recepción y responsables de las conversaciones derivadas.
- Tono, nombre y presentación del asistente virtual.

## 31.2 Información y accesos de Dentalink

- Documentación técnica vigente de la API.
- URL base y método de autenticación.
- Credenciales de prueba entregadas mediante un canal seguro.
- Operaciones disponibles: pacientes, profesionales, agenda, creación, reprogramación y cancelación.
- Campos obligatorios e identificadores utilizados por la API.
- Ambiente o datos de prueba.
- Límites de solicitudes, timeouts y reglas de reintento.
- Formato de errores y conflictos de agenda.
- Confirmación de si Dentalink ya envía recordatorios.

## 31.3 WhatsApp y Meta

- Número que utilizará el agente.
- Acceso administrativo a Meta Business Manager.
- Estado de verificación del negocio.
- WhatsApp Business Account y Phone Number ID.
- Webhook, token de verificación y App Secret.
- Plantillas aprobadas para mensajes fuera de la ventana de atención.

## 31.4 Chatwoot

- URL de la instancia.
- Account ID, Inbox ID y token de API.
- Usuarios que atenderán las conversaciones.
- Regla para pausar el agente cuando interviene una persona.
- Regla explícita para reactivarlo.
- Etiquetas y equipos de derivación.

## 31.5 Decisiones técnicas iniciales

- Proveedor principal: OpenAI.
- Persistencia durable del grafo: PostgreSQL mediante langgraph-checkpoint-postgres.
- Redis únicamente para debounce, locks, rate limiting, caché y workers.
- Worker inicial: ARQ.
- Cliente HTTP asíncrono: HTTPX.
- Docker Compose para el despliegue del MVP.
- n8n limitado a recordatorios, reportes y tareas periféricas.
- Sin búsqueda web, RAG ni múltiples agentes durante el MVP.

## 31.6 Variables de entorno adicionales

> OPENAI_API_KEY=
>
> OPENAI_MODEL=
>
> OPENAI_TIMEOUT_SECONDS=20
>
> OPENAI_MAX_RETRIES=2
>
> LANGGRAPH_CHECKPOINT_DATABASE_URL=
>
> ARQ_REDIS_URL=redis://redis:6379/1
>
> OUTBOX_MAX_ATTEMPTS=5
>
> OUTBOX_RETRY_DELAY_SECONDS=30
>
> HTTP_CONNECT_TIMEOUT_SECONDS=5
>
> HTTP_READ_TIMEOUT_SECONDS=15
>
> ENABLE_GRADIO=false
>
> ENABLE_LANGSMITH=false
>
> ENABLE_WEB_SEARCH=false

## 31.7 Archivos necesarios al iniciar el repositorio

- README.md con instrucciones de instalación y ejecución.
- requirements.txt.
- .env.example sin secretos.
- .gitignore.
- docker-compose.yml.
- Dockerfile para API y worker.
- alembic.ini y carpeta migrations/.
- pyproject.toml para Ruff, Mypy y Pytest.
- Makefile o scripts para instalar, ejecutar, probar y migrar.
- docs/architecture.md con este documento.
- docs/decisions-pending.md con decisiones todavía abiertas.

## 31.8 Primer entregable técnico

- Estructura completa del repositorio.
- FastAPI con endpoints /health, /ready y webhook simulado.
- PostgreSQL y Redis mediante Docker Compose.
- Migración inicial de base de datos.
- Configuración validada con Pydantic Settings.
- Grafo mínimo de LangGraph con estado tipado.
- Checkpointer de PostgreSQL configurado.
- FakeDentalinkGateway, FakeWhatsAppGateway, FakeChatwootGateway y FakeLLMProvider.
- Flujo simulado de consulta de disponibilidad y confirmación.
- Pruebas unitarias e integración básica.
- Logs estructurados con trace_id.

## 31.9 Criterio para conectar servicios reales

WhatsApp, Chatwoot y Dentalink se conectarán cuando el flujo simulado funcione de punta a punta, las interfaces estén definidas, las pruebas básicas pasen y la clínica haya aprobado las reglas operativas.
