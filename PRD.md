# Arquitectura — Agente de IA para Clínica Dental

## MVP — WhatsApp + YCloud + Dentalink

**Versión del PRD:** 3.0  
**Estado:** listo para inicio de desarrollo sujeto a validación de credenciales, contratos reales y reglas operativas de la clínica.

Este documento define la arquitectura, alcance, reglas operativas, observabilidad y estrategia de evaluación del MVP del agente de atención por WhatsApp para una clínica dental.

El proyecto está diseñado exclusivamente para una clínica específica.

No se desarrollará inicialmente como SaaS, sistema multi-tenant ni plataforma para múltiples clínicas.

---

# 1. Objetivo

Construir un asistente administrativo para WhatsApp capaz de resolver tres necesidades principales:

1. Gestión de turnos.
2. Consulta de obras sociales y prepagas.
3. Derivación a administración.

El agente utilizará Dentalink como fuente principal de información administrativa relacionada con:

- Pacientes.
- Profesionales.
- Especialidades.
- Disponibilidad.
- Turnos.
- Convenios / obras sociales.

YCloud será utilizado para:

- Conexión con WhatsApp.
- Recepción y envío de mensajes.
- Mensajes interactivos.
- Botones.
- Webhooks.
- Shared Team Inbox.
- Atención humana.

---

# 2. Alcance del MVP

El agente podrá:

## 2.1 Turnos

- Consultar disponibilidad.
- Consultar profesionales.
- Consultar especialidades cuando sea necesario.
- Crear turnos.
- Reprogramar turnos.
- Cancelar turnos.
- Consultar próximos turnos de un paciente.
- Confirmar operaciones antes de ejecutarlas.

## 2.2 Obras sociales

- Consultar si la clínica trabaja con una obra social o prepaga.
- Buscar convenios configurados en Dentalink.
- Consultar el convenio registrado de un paciente cuando corresponda.
- Derivar a administración cuando la cobertura específica no pueda confirmarse de forma segura.

## 2.3 Administración

- Derivar una conversación a administración.
- Pausar automáticamente al agente cuando la conversación quede en modo humano.
- Permitir que administración continúe la conversación desde YCloud.
- Derivar automáticamente casos que requieren intervención manual.

## 2.4 Mensajes de audio

- Recibir notas de voz y audios enviados por WhatsApp.
- Descargar el archivo desde YCloud mediante el worker.
- Validar tipo MIME, tamaño, duración y origen.
- Transcribir el contenido mediante un proveedor abstraído.
- Procesar la transcripción como entrada conversacional.
- Eliminar el archivo temporal después de procesarlo.
- Mantener botones obligatorios en selecciones y confirmaciones sensibles.

## 2.5 Seguimiento de propuestas de turno

- Crear una propuesta de horario con vencimiento configurable.
- Enviar un follow-up cuando el paciente no responda dentro del plazo.
- Expirar la propuesta sin crear ni cancelar una cita en Dentalink.
- Permitir buscar nuevamente la disponibilidad.
- Invalidar botones correspondientes a propuestas vencidas.

---

# 3. Fuera del alcance del MVP

No se implementará inicialmente:

- Diagnóstico médico.
- Recomendaciones médicas.
- Interpretación de síntomas.
- Tratamientos mediante IA.
- RAG.
- Base vectorial.
- Búsqueda web.
- Campañas comerciales.
- Recordatorios automáticos.
- Encuestas.
- Agente de voz en tiempo real o llamadas telefónicas.
- Facturación.
- Pagos.
- Gestión de presupuestos.
- Gestión compleja de tratamientos.
- Modificación automática de obra social del paciente.
- Chatwoot.
- Aplicación móvil.
- Panel administrativo comercial completo.
- Multi-tenancy.
- Microservicios.
- Kubernetes.
- Docker Swarm.

El objetivo es mantener el MVP pequeño, controlable, auditable y enfocado.

---

# 4. Arquitectura general

```text
                    PACIENTE
                        │
                        ▼
                    WhatsApp
                        │
                        ▼
                     YCloud
              ┌─────────┴──────────┐
              │                    │
           Webhooks          Shared Inbox
              │                    │
              ▼                    ▼
           FastAPI            Administración
              │
              ▼
       Input Processing
       ┌───────┴────────┐
       ▼                ▼
     Texto        Audio Worker
                        │
                        ▼
                  Transcripción
       └───────┬────────┘
               ▼
      Conversation Service
              │
              ▼
           LangGraph
       ┌──────┼────────┐
       │      │        │
       ▼      ▼        ▼
    Turnos Convenios Handoff
       │      │
       └──┬───┘
          ▼
     Application Layer
          │
          ▼
    Dentalink Gateway
          │
          ▼
       Dentalink


PostgreSQL
    ├── conversaciones
    ├── estados
    ├── acciones pendientes
    ├── trazas funcionales
    ├── auditoría
    └── errores

Redis
    ├── debounce
    ├── locks
    ├── cache
    └── coordinación temporal

Telegram
    └── alertas inmediatas de errores relevantes

Linear
    └── incidentes que requieren seguimiento y resolución

Promptfoo
    └── evaluación del comportamiento del agente

Worker
    ├── procesamiento de audios
    ├── follow-ups y vencimientos
    ├── outbox
    └── reintentos seguros
```

---

# 5. Stack tecnológico

## 5.1 Backend

- Python.
- FastAPI.
- Pydantic.
- SQLAlchemy Async.
- Alembic.
- HTTPX.

## 5.2 Agente

- LangGraph.
- OpenAI como proveedor inicial.
- Integración del modelo abstraída mediante interfaces.
- Proveedor de transcripción abstraído mediante interfaces.

## 5.3 Persistencia

- PostgreSQL.
- Redis.

## 5.4 Integraciones

- YCloud.
- Dentalink.

## 5.5 Observabilidad y evaluación

- Structlog.
- Telegram Bot para alertas inmediatas.
- Linear para incidentes y seguimiento.
- Promptfoo.
- Panel administrativo interno mínimo.

## 5.6 Infraestructura

- Docker.
- Docker Compose.
- Traefik o Nginx.
- GitHub Actions.
- Portainer para administración de infraestructura cuando corresponda.

---

# 6. Principio fundamental del agente

El flujo principal debe ser determinístico.

Siempre que sea posible:

```text
Botón
  ↓
Intención conocida
  ↓
LangGraph
  ↓
Caso de uso
  ↓
Dentalink
```

No se utilizará el LLM para decidir libremente qué operación realizar.

El modelo podrá:

- Interpretar lenguaje natural.
- Extraer datos.
- Interpretar fechas y referencias temporales.
- Identificar nombres.
- Detectar una obra social mencionada.
- Clasificar mensajes cuando no provengan de botones.
- Generar respuestas naturales dentro de reglas definidas.

El modelo no podrá:

- Crear turnos directamente.
- Cancelar turnos directamente.
- Reprogramar directamente.
- Ejecutar requests HTTP.
- Ejecutar SQL.
- Inventar disponibilidad.
- Inventar profesionales.
- Inventar obras sociales.
- Inventar coberturas.
- Informar que una operación fue exitosa sin confirmación real de Dentalink.
- Convertir un audio en confirmación de una operación sensible.
- Simular o fabricar el payload de un botón interactivo.

El estado de la conversación determinará las entradas válidas:

```text
FREE_INPUT
→ texto o audio

INTERACTIVE_SELECTION
→ payload de botón o lista

SENSITIVE_CONFIRMATION
→ payload vinculado a la PendingAction vigente

HUMAN
→ el agente no procesa ni responde
```

Durante `INTERACTIVE_SELECTION` o `SENSITIVE_CONFIRMATION`, un audio podrá utilizarse únicamente para detectar handoff, incomprensión o una situación fuera de alcance. Nunca ejecutará directamente una selección, creación, cancelación o reprogramación.

---

# 7. Mensaje inicial

Cuando una conversación nueva comienza, el paciente recibirá:

```text
🦷 Bienvenido a Smiling Pilar.

Soy el asistente virtual de la clínica.

¿En qué podemos ayudarte?
```

Botones:

```text
📅 Turnos
🏥 Obras sociales
💬 Administración
```

Estos botones representan las tres funciones del MVP.

---

# 8. Flujo principal

```text
Inicio
  │
  ▼
Bienvenida
  │
  ├── 📅 Turnos
  │
  ├── 🏥 Obras sociales
  │
  └── 💬 Administración
```

Si el usuario escribe directamente en lugar de utilizar los botones, el agente intentará determinar si el mensaje corresponde a:

```text
appointment
insurance
handoff
```

Si no puede determinarlo con suficiente seguridad:

1. Mostrará nuevamente las opciones principales, o
2. Derivará a administración cuando el mensaje requiera intervención humana.

---

# 9. Gestión de turnos

Al seleccionar:

```text
📅 Turnos
```

se mostrará:

```text
¿Qué querés hacer?
```

Botones:

```text
📅 Sacar turno
🔄 Reagendar
❌ Cancelar
```

---

# 10. Crear turno

Flujo:

```text
SACAR TURNO
      │
      ▼
Identificar paciente
      │
      ▼
Obtener motivo / especialidad
      │
      ▼
¿Tiene profesional preferido?
      │
  ┌───┴────┐
  │        │
  Sí       No
  │        │
  ▼        ▼
Agenda   Próxima disponibilidad
dentista por especialidad
  │        │
  └───┬────┘
      ▼
Mostrar horarios
      │
      ▼
Paciente selecciona
      │
      ▼
Revalidar disponibilidad
      │
      ▼
Crear PendingAction
      │
      ▼
Solicitar confirmación
      │
      ▼
Paciente confirma
      │
      ▼
Crear turno en Dentalink
      │
      ▼
Dentalink responde OK
      │
      ▼
Informar confirmación
```

Nunca se informará que un turno fue reservado hasta recibir una respuesta válida de Dentalink.

---

# 11. Disponibilidad

La disponibilidad deberá obtenerse desde Dentalink.

Cuando el paciente solicita un profesional específico:

```text
Profesional
     ↓
Consultar agenda
     ↓
Obtener horarios disponibles
```

Cuando el paciente no tiene preferencia:

```text
Especialidad
     ↓
Consultar próximas disponibilidades
     ↓
Mostrar mejores opciones
```

El agente podrá presentar inicialmente entre 3 y 5 opciones.

La disponibilidad deberá revalidarse inmediatamente antes de confirmar la operación.

## 11.1 Prevención de superposición

La aplicación no calculará disponibilidad únicamente desde su propia base.

Dentalink será la autoridad final para citas, bloqueos, profesionales, sucursales, sillones y recursos.

Antes de crear o reagendar:

```text
Mostrar horarios disponibles
        ↓
Paciente selecciona
        ↓
Crear propuesta temporal
        ↓
Paciente confirma
        ↓
Adquirir lock corto
        ↓
Revalidar agenda en Dentalink
        ↓
Crear o reagendar
        ↓
Dentalink responde OK
```

La superposición se evaluará sobre el intervalo completo:

```text
requested_start < existing_end
AND
requested_end > existing_start
```

También deberán coincidir o interferir:

- Profesional.
- Sucursal.
- Fecha.
- Sillón o recurso.
- Bloqueos especiales.
- Duración requerida.

Lock sugerido:

```text
lock:appointment:{sucursal}:{profesional}:{fecha}:{hora}:{recurso}
```

El lock protege solamente contra ejecuciones concurrentes de nuestra aplicación. No impide que recepción reserve directamente en Dentalink, por lo que la revalidación y la respuesta final del proveedor siguen siendo obligatorias.

## 11.2 Horario ocupado durante la confirmación

Si el horario se ocupa mientras el paciente confirma:

```text
Ese horario acaba de ocuparse mientras confirmábamos.
No se creó ningún turno.
Te muestro nuevas opciones disponibles.
```

No se reintentará automáticamente el mismo horario ni se informará éxito.

---

# 12. Profesionales

Dentalink será la fuente de verdad para:

- Profesionales.
- Especialidades.
- Estado habilitado.
- Configuración de agenda.
- Horarios.

No se mantendrá inicialmente una tabla manual de profesionales.

Se podrá utilizar cache temporal para disminuir consultas repetidas.

---

# 13. Reprogramar turno

Flujo:

```text
REAGENDAR
    │
    ▼
Identificar paciente
    │
    ▼
Consultar próximas citas
    │
    ▼
Mostrar citas
    │
    ▼
Paciente selecciona
    │
    ▼
Buscar nueva disponibilidad
    │
    ▼
Mostrar opciones
    │
    ▼
Seleccionar horario
    │
    ▼
Revalidar disponibilidad
    │
    ▼
Crear PendingAction
    │
    ▼
Confirmación explícita
    │
    ▼
Modificar cita en Dentalink
    │
    ▼
Dentalink responde OK
    │
    ▼
Confirmar nueva fecha
```

No se eliminará y volverá a crear una cita si Dentalink dispone de una operación específica para cambiar la fecha.

---

# 14. Cancelar turno

Flujo:

```text
CANCELAR
   │
   ▼
Identificar paciente
   │
   ▼
Consultar próximas citas
   │
   ▼
Mostrar citas
   │
   ▼
Seleccionar cita
   │
   ▼
Crear PendingAction
   │
   ▼
¿Confirmás cancelar?
   │
   ▼
Sí
   │
   ▼
Actualizar estado en Dentalink
   │
   ▼
Dentalink responde OK
   │
   ▼
Informar cancelación
```

La cancelación deberá utilizar el estado de anulación configurado en Dentalink.

No se deberá hardcodear un identificador de estado.

---

# 15. Confirmación explícita

Crear, reprogramar y cancelar son operaciones sensibles.

Siempre deberán requerir confirmación.

Ejemplo:

```text
Tengo disponible:

Dra. Laura Pérez
Martes 12 de agosto
15:30 hs

¿Confirmás que querés reservar este turno?
```

Botones:

```text
✅ Confirmar
❌ Cancelar
```

Solamente después de recibir una confirmación válida podrá ejecutarse la operación.

---

# 16. Pending Actions

Cada operación sensible deberá crear previamente una acción pendiente.

Tabla conceptual:

```text
pending_actions

id
conversation_id
action_type
payload
status
expires_at
created_at
confirmed_at
executed_at
```

Tipos:

```text
create_appointment
reschedule_appointment
cancel_appointment
```

Estados:

```text
pending
confirmed
executing
completed
cancelled
expired
failed
```

Las acciones pendientes deberán persistirse en PostgreSQL.

## 16.1 Propuestas de horario y vencimiento

Una `PendingAction` representa una intención pendiente de confirmación.

No representa una reserva temporal en Dentalink.

```text
PendingAction = propuesta
Turno Dentalink = reserva real
```

La propuesta tendrá un vencimiento configurable, inicialmente de 120 segundos.

Si el paciente no responde dentro del plazo:

1. La acción cambia atómicamente de `pending` a `expired`.
2. Se invalidan sus botones.
3. Se restauran los campos de selección de fecha, hora y recurso.
4. Se conserva paciente, especialidad y profesional preferido cuando corresponda.
5. Se crea un mensaje mediante outbox.

Mensaje sugerido:

```text
El horario seleccionado venció porque no recibimos tu confirmación.
No se reservó ningún turno.

Si todavía querés continuar, podemos buscar nuevamente la disponibilidad.
```

Botones:

```text
🔎 Buscar nuevamente
💬 Administración
🏠 Menú principal
```

## 16.2 Scheduled Actions

Los follow-ups y vencimientos deberán persistirse en PostgreSQL.

Tabla conceptual:

```text
scheduled_actions

id
conversation_id
pending_action_id
action_type
status
scheduled_for
attempts
idempotency_key
last_error
created_at
cancelled_at
executed_at
```

Tipo inicial:

```text
appointment_confirmation_timeout
```

Estados:

```text
scheduled
processing
completed
cancelled
failed
```

La `PendingAction`, la `ScheduledAction` y el evento outbox inicial se crearán en la misma transacción.

## 16.3 Ejecución del follow-up

El worker buscará acciones cuyo `scheduled_for <= now()`.

Antes de ejecutar:

1. Adquirir lock de conversación.
2. Bloquear la fila con `FOR UPDATE SKIP LOCKED`.
3. Verificar que la acción siga en `pending`.
4. Verificar que no exista una respuesta válida posterior.
5. Expirar atómicamente la acción.
6. Crear el mensaje en outbox.
7. Marcar la tarea como completada.

El follow-up deberá cancelarse cuando:

- El paciente confirma.
- El paciente rechaza.
- Selecciona otro horario.
- Solicita administración.
- La conversación pasa a `HUMAN`.
- Se completa la operación.
- Otra acción reemplaza la anterior.

Si una confirmación y el vencimiento ocurren simultáneamente, solamente una transición podrá ganar:

```text
pending → confirmed

o

pending → expired
```

Un botón perteneciente a una acción expirada nunca ejecutará una operación. Deberá volver a consultar Dentalink.

---

# 17. Idempotencia

El sistema deberá impedir operaciones duplicadas.

## 17.1 Mensajes

Cada mensaje recibido tendrá:

```text
external_message_id UNIQUE
```

## 17.2 Turnos

Cada operación tendrá:

```text
idempotency_key UNIQUE
```

Ejemplo:

```text
create:conversation-123:pending-action-456
```

PostgreSQL será responsable de garantizar la idempotencia durable.

Redis podrá utilizarse adicionalmente para bloqueos temporales.

---

# 18. Obras sociales y prepagas

Dentalink será la fuente de verdad para los convenios de la clínica.

Flujo:

```text
Paciente:
"¿Trabajan con OSDE?"

        │
        ▼
Extraer / normalizar nombre
        │
        ▼
Consultar convenios Dentalink
        │
        ▼
Buscar coincidencia
        │
    ┌───┴────┐
    │        │
 Encontrado  No encontrado
    │        │
    ▼        ▼
Responder   Informar que no
según dato  aparece disponible
real
```

El agente no deberá inventar información sobre cobertura.

---

# 19. Consulta de convenio del paciente

Cuando corresponda, el sistema podrá:

```text
Identificar paciente
      │
      ▼
Consultar convenios asociados
      │
      ▼
Mostrar convenio registrado
```

El MVP permitirá consultar.

No permitirá:

- Crear convenio.
- Cambiar convenio.
- Eliminar convenio.

Esas operaciones permanecerán en administración.

---

# 20. Preguntas sobre cobertura

Preguntas como:

```text
"¿Trabajan con OSDE?"
```

podrán resolverse automáticamente.

Preguntas como:

```text
"¿Cuánto me cubre OSDE en una corona?"
```

solamente deberán responderse si Dentalink contiene información suficiente y verificable.

Si no existe información confiable:

```text
Esta consulta necesita ser revisada por administración.
¿Querés que te comunique con ellos?
```

El sistema nunca inventará porcentajes, montos ni condiciones de cobertura.

---

# 21. Handoff a administración

El paciente podrá seleccionar directamente:

```text
💬 Administración
```

Respuesta:

```text
Perfecto. Te comunico con administración de la clínica.

Podrán continuar la conversación desde este mismo chat.
```

Luego:

```text
conversation_mode = HUMAN
```

Cuando una conversación está en modo humano:

```text
LangGraph NO responde automáticamente.
```

---

# 22. Casos de derivación automática

Además del botón manual, se podrá derivar automáticamente ante mensajes como:

```text
"Voy a llegar tarde."

"Estoy llegando."

"Necesito hablar con una persona."

"Me equivoqué con el turno."

"Tengo un problema con mi turno."

"No aparece mi turno."

"Quiero hablar con administración."
```

No se intentará modificar automáticamente un turno porque el paciente indique que llegará tarde.

Ese caso siempre se deriva.

---

# 23. Estado de conversación

La conversación tendrá:

```text
conversation_mode
```

Valores:

```text
BOT
HUMAN
CLOSED
```

## BOT

El agente puede responder.

## HUMAN

Administración controla la conversación.

LangGraph queda bloqueado.

## CLOSED

Conversación finalizada.

El estado se almacenará en PostgreSQL.

YCloud no será la única fuente de verdad para saber si el agente puede responder.

---

# 24. YCloud

YCloud reemplaza completamente a Chatwoot.

Sus responsabilidades serán:

- WhatsApp Business API.
- Recepción de mensajes.
- Webhooks.
- Envío de mensajes.
- Botones.
- Listas interactivas cuando sean necesarias.
- Shared Team Inbox.
- Atención humana.

La aplicación tendrá un adaptador específico.

```text
infrastructure/
└── ycloud/
    ├── client.py
    ├── webhook_parser.py
    ├── messaging_gateway.py
    ├── handoff_gateway.py
    ├── schemas.py
    └── exceptions.py
```

## 24.1 Mensajes entrantes de audio

YCloud entregará los audios mediante eventos `whatsapp.inbound_message.received` con `type = audio` y metadatos del archivo.

El webhook deberá persistir el mensaje y responder rápidamente. La descarga y transcripción se ejecutarán en el worker.

```text
Webhook YCloud
      ↓
Validar firma e idempotencia
      ↓
Persistir mensaje
      ↓
Crear media_processing_job
      ↓
Responder 200
      ↓
Worker descarga audio
      ↓
Validar origen, MIME, tamaño y duración
      ↓
Transcribir
      ↓
Normalizar texto
      ↓
LangGraph
```

No se transcribirá dentro del request HTTP del webhook.

## 24.2 Estados de entrada

La transcripción se procesará como si fuera texto únicamente cuando el estado permita entrada libre.

| Estado | Texto | Audio | Botón |
|---|---:|---:|---:|
| `FREE_INPUT` | Sí | Sí | Sí |
| `INTERACTIVE_SELECTION` | No avanza | No avanza | Sí |
| `SENSITIVE_CONFIRMATION` | No confirma | No confirma | Sí |
| `HUMAN` | No procesa | No procesa | No procesa |

Excepciones globales permitidas desde texto o audio:

- Solicitar administración.
- Indicar que no comprende.
- Informar una urgencia o situación fuera de alcance.

Estas excepciones no ejecutan operaciones sensibles.

## 24.3 Seguridad y privacidad del audio

- Descargar únicamente URLs autorizadas de YCloud.
- Enviar la credencial requerida sin registrarla.
- Validar hash cuando esté disponible.
- Rechazar tipos MIME no permitidos.
- Aplicar límites de tamaño y duración.
- Aplicar rate limiting por conversación.
- No almacenar permanentemente el archivo en el MVP.
- Eliminar el temporal después de transcribir o fallar definitivamente.
- No enviar transcripciones completas a Telegram o Linear.
- Definir retención de transcripciones antes del piloto.

## 24.4 Audio recibido durante un vencimiento

Si un audio llegó antes de `expires_at` pero todavía se está transcribiendo, el vencimiento no deberá ganar únicamente por demora interna del sistema.

Se utilizará `inbound_received_at`, no la hora de finalización de la transcripción.

El audio podrá pausar una vez el vencimiento mientras se procesa, pero nunca confirmará por sí solo un turno.

Si la transcripción dice “sí, confirmo”, el agente responderá:

```text
Para confirmar la reserva necesito que presiones el botón Confirmar.
```

---

# 25. Messaging Gateway

Interfaz conceptual:

```python
class MessagingGateway(Protocol):

    async def send_text(
        self,
        conversation_id: str,
        text: str,
    ) -> None:
        ...

    async def send_buttons(
        self,
        conversation_id: str,
        text: str,
        buttons: list,
    ) -> None:
        ...
```

Implementación inicial:

```text
YCloudMessagingGateway
```

---

# 26. Human Handoff Gateway

Interfaz conceptual:

```python
class HumanHandoffGateway(Protocol):

    async def handoff(
        self,
        conversation_id: str,
        context: dict,
    ) -> None:
        ...
```

Implementación:

```text
YCloudHandoffGateway
```

---

# 27. Dentalink Gateway

Dentalink deberá permanecer encapsulado detrás de interfaces de aplicación.

LangGraph nunca utilizará directamente el cliente HTTP.

Interfaz conceptual:

```python
class AppointmentGateway(Protocol):

    async def search_availability(...):
        ...

    async def list_professionals(...):
        ...

    async def get_patient_appointments(...):
        ...

    async def create_appointment(...):
        ...

    async def reschedule_appointment(...):
        ...

    async def cancel_appointment(...):
        ...
```

Para convenios:

```python
class AgreementGateway(Protocol):

    async def list_agreements(...):
        ...

    async def find_agreement_by_name(...):
        ...

    async def get_patient_agreements(...):
        ...
```

Implementación:

```text
DentalinkGateway
```

## 27.1 Endpoints Dentalink verificados para el MVP

Base documentada:

```text
https://api.dentalink.healthatom.com/api
```

Autenticación:

```http
Authorization: Token {access_token}
```

| Funcionalidad | Método y endpoint | Uso en el MVP |
|---|---|---|
| Sucursales | `GET /v1/sucursales` | Resolver sucursal |
| Profesionales | `GET /v1/dentistas` | Listar profesionales |
| Profesional | `GET /v1/dentistas/{id_dentista}` | Obtener detalle |
| Horarios habituales | `GET /v1/dentistas/{id_dentista}/horarios` | Contexto de agenda |
| Horarios especiales | `GET /v1/dentistas/{id_dentista}/horariosespeciales` | Excepciones |
| Horarios bloqueados | `GET /v1/dentistas/{id_dentista}/horariosbloqueados` | Bloqueos |
| Disponibilidad puntual | `GET /v5/agendas` | Buscar espacios libres |
| Agenda detallada | `GET /v1/sucursales/{id_sucursal}/dentistas/{id_dentista}/agendas` | Citas y bloqueos por rango |
| Citas del profesional | `GET /v1/dentistas/{id_dentista}/citas` | Consulta administrativa protegida |
| Citas de sucursal | `GET /v1/sucursales/{id_sucursal}/citas` | Consulta administrativa protegida |
| Citas generales | `GET /v1/citas` | Filtros por fecha, dentista y estado |
| Detalle de cita | `GET /v1/citas/{id_cita}` | Revalidación |
| Buscar pacientes | `GET /v1/pacientes` | Identificación |
| Citas del paciente | `GET /v1/pacientes/{id_paciente}/citas` | Próximos turnos propios |
| Crear cita | `POST /v1/citas/` | Crear turno confirmado |
| Reagendar | `POST /v1/citas/changeDate` | Cambiar fecha y horario |
| Actualizar/cancelar | `PUT /v1/citas/{id_cita}` | Cambiar estado |
| Estados de citas | `GET /v1/citas/estados` | Resolver estado de anulación |
| Especialidades | `GET /v1/especialidades` | Listar especialidades |
| Próxima disponibilidad | `GET /v1/especialidades/{id_especialidad}/proxima` | Primera opción |
| Disponibilidad por rango | `GET /v1/especialidades/{id_especialidad}/rangoProxima` | Varias opciones |
| Convenios | `GET /v1/convenios` | Obras sociales aceptadas |
| Convenios del paciente | `GET /v1/pacientes/{id_paciente}/convenios` | Cobertura registrada |

## 27.2 Disponibilidad recomendada

Para ofrecer horarios se utilizará principalmente:

```http
GET /api/v5/agendas
```

Filtro conceptual:

```json
{
  "id_sucursal": {"eq": 1},
  "fecha": {"eq": "2026-08-15"},
  "duracion": {"eq": 30},
  "id_profesional": {"eq": 626}
}
```

Si el paciente no elige profesional, se podrá omitir `id_profesional` para consultar profesionales con agenda online disponible en la sucursal.

## 27.3 Creación de cita

`POST /api/v1/citas/` requiere como mínimo validar:

```text
id_dentista
id_especialidad
id_sucursal
id_sillon
id_paciente
fecha
hora_inicio
duracion
```

La duración deberá ser compatible con el intervalo del profesional.

Antes del piloto deberá consultarse con la clínica el comportamiento de Dentalink respecto de tratamientos, ya que la API documenta que puede buscar o generar un tratamiento “Diagnóstico” cuando no se especifica uno y la configuración lo permite.

## 27.4 Reprogramación

Se utilizará:

```http
POST /api/v1/citas/changeDate
```

La documentación denomina `id_sesion` al identificador de la cita que se modifica. Este contrato deberá cubrirse con tests y verificarse en el ambiente real.

## 27.5 Cancelación

Dentalink no documenta la cancelación como `DELETE`.

Se utilizará:

```http
PUT /api/v1/citas/{id_cita}
```

cambiando `id_estado` por un estado de anulación obtenido dinámicamente desde:

```http
GET /api/v1/citas/estados
```

Nunca se hardcodeará el ID del estado.

## 27.6 Inconsistencias documentales a verificar

- Dentalink mezcla `dentista` y `profesional` según la versión.
- `/v5/agendas` devuelve `id_profesional`, mientras crear cita utiliza `id_dentista`.
- `changeDate` utiliza `id_sesion` para la cita.
- La documentación muestra tanto `mostrar_detalles` como `mostar_detalles`.
- Debe verificarse si la clínica permite citas sin plan de tratamiento.
- Deben comprobarse paginación, rate limits y códigos reales de conflicto.

Estas diferencias se aislarán dentro de `DentalinkGateway` y se cubrirán mediante contract tests.

## 27.7 Privacidad de agendas

El agente del paciente podrá consultar disponibilidad y los turnos del paciente identificado.

No podrá mostrar la agenda completa de un profesional ni datos de otros pacientes.

Los endpoints de citas por profesional o sucursal quedarán reservados para un flujo administrativo autenticado y no forman parte de las respuestas públicas del bot.

---

# 28. Casos de uso

## 28.1 Turnos

```text
SearchAvailabilityUseCase
ListProfessionalsUseCase
GetPatientAppointmentsUseCase
CreateAppointmentUseCase
RescheduleAppointmentUseCase
CancelAppointmentUseCase
```

## 28.2 Obras sociales

```text
ListAgreementsUseCase
FindAgreementByNameUseCase
GetPatientAgreementsUseCase
```

## 28.3 Conversación

```text
RequestHumanHandoffUseCase
SetConversationModeUseCase
SendMessageUseCase
ConfirmPendingActionUseCase
IdentifyPatientUseCase
```

## 28.4 Audio y follow-up

```text
ProcessInboundAudioUseCase
TranscribeAudioUseCase
ExpirePendingActionUseCase
CancelScheduledActionUseCase
SearchAvailabilityAgainUseCase
```

Interfaz conceptual:

```python
class TranscriptionGateway(Protocol):

    async def transcribe(
        self,
        audio_path: str,
        mime_type: str,
    ) -> str:
        ...
```

---

# 29. LangGraph

El grafo debe mantenerse pequeño.

```text
receive_message
      │
      ▼
check_conversation_mode
      │
      ▼
resolve_interaction
      │
      ├─────────────┬────────────┐
      ▼             ▼            ▼
 appointment     agreement     handoff
      │             │            │
      ▼             ▼            ▼
appointment      lookup        HUMAN
flow
```

También existirá:

```text
fallback
```

que podrá:

- Mostrar nuevamente el menú.
- Solicitar información.
- Derivar a administración.

Además existirá un manejo de errores común:

```text
handle_error
```

Su función será decidir el comportamiento conversacional cuando una operación falla.

No reemplaza el sistema de logs ni de observabilidad.

---

# 30. Manejo de errores dentro del grafo

Los nodos críticos deberán ejecutarse mediante wrappers controlados.

Conceptualmente:

```text
search_availability
       │
       ▼
    ERROR
       │
       ├── registrar error
       ├── registrar ejecución del nodo
       ├── registrar tool execution
       ├── actualizar agent_run
       │
       ▼
 handle_error
       │
       ├── retry seguro
       ├── fallback
       └── handoff
```

Un error técnico no deberá dejar la conversación en un estado inconsistente.

---

# 31. Estado del agente

El estado de LangGraph contendrá únicamente información conversacional.

Ejemplo:

```python
class AgentState(TypedDict):

    conversation_id: str

    user_message: str

    intent: str | None

    appointment_action: str | None

    collected_data: dict

    missing_fields: list[str]

    pending_action_id: str | None

    requires_handoff: bool

    response_text: str | None
```

Las operaciones importantes nunca deberán existir únicamente dentro del estado del grafo.

---

# 32. Identificación del paciente

El teléfono de WhatsApp no será considerado prueba suficiente para operaciones sensibles.

Para:

- Ver turnos.
- Cancelar.
- Reprogramar.

se deberán solicitar los datos que la clínica determine.

Posibles datos:

```text
Nombre y apellido
DNI
Fecha de nacimiento
Teléfono registrado
```

La regla definitiva deberá ser aprobada por la clínica.

Ejemplo inicial:

```text
Nombre completo + DNI
```

Los datos deberán validarse contra Dentalink.

---

# 33. PostgreSQL

PostgreSQL será la fuente de verdad de nuestra aplicación.

Tablas iniciales:

```text
conversations
messages
conversation_states

pending_actions
appointment_actions
scheduled_actions
media_processing_jobs

agent_runs
node_executions
tool_executions
errors

outbox_events
```

La tabla `messages` deberá contemplar:

```text
message_type
media_id
media_mime_type
media_sha256
media_status
inbound_received_at
transcription
transcription_status
transcription_provider
transcription_model
transcription_duration_ms
transcription_error
```

Estados de procesamiento de medios:

```text
pending
downloading
transcribing
completed
failed
rejected
```

Opcional:

```text
system_settings
```

No se crearán inicialmente tablas propias para:

```text
professionals
insurance_providers
appointments
treatments
prices
```

si Dentalink ya provee esa información.

---

# 34. Redis

Redis será utilizado únicamente para información temporal.

Usos:

```text
Debounce
Locks
Cache
Rate limiting
Coordinación temporal
Idempotencia temporal
```

Redis no será fuente de verdad.

Una caída de Redis no deberá eliminar:

- Conversaciones.
- Acciones pendientes.
- Estado humano.
- Auditoría.
- Trazas de ejecución.

---

# 35. Cache

Información relativamente estable podrá cachearse temporalmente.

Ejemplos:

```text
Profesionales
Especialidades
Convenios
```

TTL inicial sugerido:

```text
10 a 30 minutos
```

Nunca se cacheará disponibilidad durante períodos largos.

La disponibilidad deberá revalidarse antes de confirmar un turno.

---

# 36. Outbox

Se utilizará `outbox_events` para evitar repetir operaciones cuando falle solamente el envío del mensaje.

Ejemplo:

```text
Dentalink crea turno
      │
      ▼
PostgreSQL registra operación
      │
      ▼
Outbox registra mensaje
      │
      ▼
YCloud falla
      │
      ▼
Worker reintenta mensaje
```

No se vuelve a crear el turno.

---

# 37. Debounce

Los mensajes consecutivos deberán agruparse.

Ejemplo:

```text
Hola

Necesito turno

para limpieza

mañana
```

se podrá procesar como:

```text
Hola. Necesito turno para limpieza mañana.
```

Configuración inicial:

```text
MESSAGE_DEBOUNCE_SECONDS=5
```

---

# 38. Observabilidad del agente

La observabilidad del agente será parte del MVP.

El objetivo es poder responder rápidamente:

1. ¿Qué paciente estaba conversando?
2. ¿Qué mensaje inició la ejecución?
3. ¿Qué intentaba hacer el agente?
4. ¿En qué nodo falló?
5. ¿Qué herramienta o integración falló?
6. ¿Qué respuesta terminó recibiendo el paciente?

La observabilidad tendrá cuatro componentes:

```text
PostgreSQL → trazabilidad funcional
Panel /admin → inspección de conversaciones
Structlog → logs estructurados
Telegram → alertas inmediatas
Linear → incidentes que requieren acción
```

---

# 39. Agent Runs

Cada procesamiento de un mensaje tendrá un `agent_run`.

Tabla conceptual:

```text
agent_runs

id
conversation_id
message_id
trace_id

prompt_version
model

started_at
finished_at

status
current_node

error_id
```

Estados posibles:

```text
running
completed
failed
handoff
```

---

# 40. Node Executions

Cada nodo importante de LangGraph deberá registrar su ejecución.

Tabla conceptual:

```text
node_executions

id
agent_run_id

node_name

started_at
finished_at

status

input_summary
output_summary

duration_ms
error_id
```

Ejemplo:

```text
run_83921

✓ resolve_interaction
✓ identify_patient
✗ search_availability
✓ handoff
```

Esto permitirá identificar exactamente dónde falló una conversación.

---

# 41. Tool Executions

Las llamadas a herramientas y servicios externos deberán registrarse separadamente.

Tabla conceptual:

```text
tool_executions

id
agent_run_id
node_execution_id

tool_name
provider
operation

request_summary
response_summary

status
http_status
duration_ms

error_id
created_at
```

Ejemplo:

```text
tool_name:
SearchAvailabilityTool

provider:
dentalink

operation:
search_availability

status:
failed

http_status:
timeout

duration_ms:
15023
```

Nunca se deberán guardar tokens, credenciales ni información sensible innecesaria.

---

# 42. Errors

Tabla conceptual:

```text
errors

id

trace_id
conversation_id
agent_run_id

source
error_type
error_code

message
technical_detail

severity
retryable

created_at
resolved_at
```

Fuentes posibles:

```text
dentalink
ycloud
openai
postgresql
redis
langgraph
application
```

---

# 43. Clasificación de errores

## 43.1 Business Errors

```text
patient_not_found
appointment_not_found
appointment_slot_taken
agreement_not_found
```

Estos no necesariamente representan una falla del sistema.

## 43.2 Integration Errors

```text
dentalink_timeout
dentalink_auth_error
dentalink_invalid_response
ycloud_error
openai_timeout
```

## 43.3 System Errors

```text
database_error
redis_error
unexpected_exception
```

## 43.4 Agent Errors

```text
invalid_llm_output
invalid_tool_arguments
unknown_intent
graph_state_error
```

---

# 44. Panel administrativo mínimo

Se implementará un panel interno básico.

No será un CRM ni un sistema comercial completo.

Rutas mínimas:

```text
/admin/conversations
/admin/errors
/admin/runs/{id}
```

## 44.1 Conversaciones

Debe permitir ver:

- Paciente o identificador interno.
- Estado BOT / HUMAN.
- Último mensaje.
- Resultado.
- Errores asociados.

Ejemplo:

```text
Paciente        Estado     Último mensaje          Resultado
Juan Pérez      HUMAN      Quiero reagendar...     ⚠ Error
María López     BOT        Tengo OSDE              ✓ Resuelto
Pedro Gómez     BOT        Quiero turno            ✓ Resuelto
```

## 44.2 Detalle de conversación

Debe mostrar:

- Mensajes del paciente.
- Mensajes del agente.
- Agent runs asociados.
- Nodos ejecutados.
- Tools ejecutadas.
- Errores.
- Handoff.

Ejemplo:

```text
Paciente:
Quiero pasar el turno para mañana.

Agente:
¿Qué horario preferís?

Paciente:
A la tarde.

TRACE

✓ resolve_interaction
✓ identify_patient
✓ get_appointments
✗ search_availability
✓ fallback
✓ human_handoff
```

## 44.3 Detalle de error

Debe mostrar:

```text
Nodo
Tool
Provider
Operación
Fecha
Duración
Estado
HTTP status
Error type
Mensaje técnico
Retryable
Trace ID
Agent Run ID
```

Desde un error se deberá poder acceder a la conversación relacionada.

Desde una conversación se deberá poder acceder a la ejecución relacionada.

---

# 45. Sistema de alertas

El sistema deberá diferenciar entre:

```text
evento registrado
alerta operativa
incidente que requiere intervención
```

No todos los errores generarán notificaciones.

Flujo general:

```text
ERROR
  │
  ▼
ErrorService
  │
  ├── registrar en PostgreSQL
  ├── registrar en Structlog
  │
  ▼
clasificar severidad
  │
  ├── INFO
  ├── WARNING
  ├── ERROR
  └── CRITICAL
```

Según la severidad se decidirá si corresponde:

```text
guardar únicamente
avisar por Telegram
crear / actualizar incidente en Linear
```

---

# 46. Niveles de severidad

## INFO

Eventos normales del negocio.

Ejemplos:

```text
patient_not_found
agreement_not_found
appointment_not_found
```

Acciones:

```text
PostgreSQL
Structlog
```

No generan alerta.

## WARNING

Situaciones anómalas que todavía no requieren intervención inmediata.

Ejemplos:

```text
appointment_slot_taken
invalid_llm_output aislado
dentalink_timeout aislado
unknown_intent repetido
```

Acciones:

```text
PostgreSQL
Structlog
Panel /admin
```

## ERROR

Problemas técnicos repetidos o que afectan parcialmente el funcionamiento.

Ejemplos:

```text
dentalink_timeout repetido
ycloud_send_failure repetido
openai_timeout repetido
graph_state_error
```

Acciones:

```text
PostgreSQL
Structlog
Telegram
```

Linear podrá crearse si el problema supera el umbral definido.

## CRITICAL

Problemas que requieren intervención inmediata.

Ejemplos:

```text
dentalink_auth_error
ycloud_auth_error
ycloud_webhook_failure
database_error
unexpected_exception crítica
```

Acciones:

```text
PostgreSQL
Structlog
Telegram
Linear
```

---

# 47. Telegram

Telegram será utilizado como canal de alerta inmediata para el administrador técnico del agente.

No será fuente de verdad.

Ejemplo de alerta:

```text
🚨 ERROR CRÍTICO — Agente Smiling Pilar

Servicio: Dentalink
Nodo: search_availability
Error: AuthenticationError

Conversaciones afectadas: 4
Primera detección: 00:31

Issue Linear:
CLI-42

Ver detalle:
https://agente.example.com/admin/errors/err_8291
```

Telegram no deberá recibir:

- DNI.
- Teléfonos completos.
- Historia clínica.
- Conversaciones completas.
- Tokens.
- API keys.
- Datos médicos.

Se utilizarán identificadores internos y enlaces al panel `/admin`.

---

# 48. Linear

Linear será utilizado como sistema de incidentes y seguimiento técnico.

Su objetivo será responder:

```text
¿Qué problema requiere intervención?
¿Qué prioridad tiene?
¿Cuántas veces ocurrió?
¿Cuándo comenzó?
¿Sigue ocurriendo?
¿Fue resuelto?
```

Ejemplo de issue:

```text
[CRITICAL][DENTALINK] Authentication failure

Priority:
Urgent

Occurrences:
18

Affected conversations:
11

First seen:
00:31

Last seen:
00:38

Fingerprint:
dentalink:authentication_error:search_availability

Admin:
https://agente.example.com/admin/errors/err_8291
```

Linear no almacenará conversaciones completas ni datos sensibles de pacientes.

---

# 49. Deduplicación de incidentes

No se deberá crear un issue nuevo por cada error.

Cada error agrupable tendrá un fingerprint.

Ejemplo:

```text
provider
+
error_type
+
operation
```

Resultado:

```text
dentalink:timeout:search_availability
```

Tabla conceptual:

```text
incidents

id
fingerprint
source
error_type
operation
severity
occurrences
affected_conversations
first_seen
last_seen
status
linear_issue_id
last_notification_at
resolved_at
```

Si ya existe un incidente abierto con el mismo fingerprint:

```text
actualizar occurrences
actualizar last_seen
actualizar affected_conversations
NO crear otro issue
```

---

# 50. Umbrales de alerta

Los errores repetitivos utilizarán umbrales para evitar ruido.

Configuración inicial sugerida:

```text
Dentalink timeout aislado
→ WARNING

5 timeouts en 2 minutos
→ ERROR
→ Telegram

10 timeouts en 5 minutos
→ crear / actualizar Linear
```

Los valores deberán ser configurables.

Variables sugeridas:

```env
ALERT_TIMEOUT_THRESHOLD_COUNT=5
ALERT_TIMEOUT_THRESHOLD_WINDOW_SECONDS=120

INCIDENT_THRESHOLD_COUNT=10
INCIDENT_THRESHOLD_WINDOW_SECONDS=300

TELEGRAM_ALERT_COOLDOWN_SECONDS=900
```

---

# 51. Recuperación de incidentes

El sistema deberá detectar cuando un incidente deja de ocurrir.

Ejemplo:

```text
🚨 00:31
Dentalink no responde.

...

✅ 00:47
Dentalink volvió a responder.

Duración:
16 minutos

Conversaciones afectadas:
23

Linear:
CLI-42
```

Cuando un servicio se recupera:

```text
incident.status = recovered
resolved_at = timestamp
```

Se podrá:

- Enviar mensaje de recuperación por Telegram.
- Agregar comentario al issue de Linear.
- Actualizar el issue.
- Cerrar el incidente interno.

El cierre automático del issue de Linear será opcional.

---

# 52. ErrorService

Toda la lógica de clasificación y alertas deberá concentrarse detrás de un servicio.

Conceptualmente:

```python
class ErrorService:

    async def report(
        self,
        error: ErrorRecord,
    ) -> None:
        ...

    async def classify(...):
        ...

    async def update_incident(...):
        ...

    async def notify_telegram(...):
        ...

    async def sync_linear(...):
        ...
```

Flujo:

```text
Node / Gateway
      │
      ▼
ErrorService
      │
      ├── ErrorsRepository
      ├── IncidentRepository
      ├── TelegramNotifier
      └── LinearIncidentGateway
```

La lógica del agente no deberá conocer directamente Telegram ni Linear.

---

# 53. Telegram Notifier

Interfaz conceptual:

```python
class AlertNotifier(Protocol):

    async def send_alert(
        self,
        alert: Alert,
    ) -> None:
        ...

    async def send_recovery(
        self,
        incident: Incident,
    ) -> None:
        ...
```

Implementación:

```text
TelegramAlertNotifier
```

---

# 54. Linear Incident Gateway

Interfaz conceptual:

```python
class IncidentGateway(Protocol):

    async def create_incident(
        self,
        incident: Incident,
    ) -> str:
        ...

    async def update_incident(
        self,
        external_id: str,
        incident: Incident,
    ) -> None:
        ...

    async def mark_recovered(
        self,
        external_id: str,
        incident: Incident,
    ) -> None:
        ...
```

Implementación:

```text
LinearIncidentGateway
```

---

# 55. Privacidad de alertas e incidentes

Telegram y Linear no serán utilizados para almacenar información clínica.

Nunca se enviará intencionalmente:

- DNI.
- Nombre completo si no es estrictamente necesario.
- Teléfono.
- Historia clínica.
- Contenido completo de conversaciones.
- Tokens.
- API keys.
- Payloads completos de Dentalink.

Se enviarán únicamente:

```text
conversation_id
agent_run_id
trace_id
node_name
tool_name
provider
operation
error_type
severity
fingerprint
occurrences
```

El contexto completo se consultará desde el panel interno `/admin`.

---

# 56. Structlog

La aplicación utilizará logs estructurados en JSON.

Campos sugeridos:

```text
timestamp
level

trace_id
conversation_id
message_id
agent_run_id

node_name
tool_name
provider
operation

duration_ms
status
error_type
```

Los logs permitirán depuración técnica adicional.

No deberán utilizarse como única fuente de auditoría.

---

# 57. Prompt versioning

Cada versión del system prompt deberá tener una versión identificable.

Ejemplo:

```text
agent-system-v0.1.0
agent-system-v0.2.0
```

Cada `agent_run` registrará:

```text
prompt_version
model
```

Esto permitirá identificar qué versión del prompt atendió una conversación determinada.

---

# 58. Promptfoo

Promptfoo se utilizará para evaluar el comportamiento del agente antes de pasar cambios a producción.

Estructura:

```text
evals/
├── promptfooconfig.yaml
│
├── prompts/
│   └── agent_system_prompt.txt
│
├── datasets/
│   ├── appointments.yaml
│   ├── agreements.yaml
│   ├── handoff.yaml
│   ├── safety.yaml
│   └── adversarial.yaml
│
└── assertions/
    └── custom.js
```

---

# 59. Categorías de evaluación

## 59.1 Turnos

Probar:

- Crear turno.
- Reprogramar.
- Cancelar.
- Solicitar confirmación.
- No ejecutar antes de confirmar.
- No inventar disponibilidad.
- No inventar profesionales.
- Manejar paciente no encontrado.
- Manejar horario ocupado.

## 59.2 Convenios

Probar:

- Reconocer obras sociales.
- Normalizar nombres.
- Consultar Dentalink.
- No inventar convenios.
- No inventar cobertura.
- Derivar preguntas de cobertura compleja.

## 59.3 Handoff

Probar frases como:

```text
"Voy a llegar tarde."
"Quiero hablar con alguien."
"Estoy llegando."
"No aparece mi turno."
"Necesito administración."
```

Resultado esperado:

```text
handoff = true
conversation_mode = HUMAN
```

## 59.4 Seguridad

Probar:

- Prompt injection.
- Solicitud de datos de otros pacientes.
- Intentos de cancelar sin confirmación.
- Intentos de modificar turnos de terceros.
- Pedido de diagnóstico.
- Pedido de medicación.
- Intentos de hacer que el modelo ignore sus instrucciones.

## 59.5 Audio y entradas estructuradas

Probar:

- Audio en entrada libre.
- Audio durante selección interactiva.
- Audio durante confirmación sensible.
- Transcripción ambigua.
- Transcripción que intenta fabricar un payload.
- Solicitud de handoff por audio.
- Audio recibido antes del vencimiento de una propuesta.

Resultado obligatorio:

```text
La transcripción puede aportar intención y datos.
Nunca reemplaza un payload interactivo obligatorio.
```

---

# 60. Evaluación aislada del prompt

Primer nivel:

```text
Promptfoo
   ↓
System Prompt
   ↓
LLM
```

Servirá para probar:

- Clasificación.
- Extracción.
- Tono.
- Reglas.
- Seguridad.
- Handoff.
- Interpretación de mensajes.

---

# 61. Evaluación del agente completo

Segundo nivel:

```text
Promptfoo
   ↓
FastAPI
   ↓
LangGraph
   ↓
FakeDentalinkGateway
   ↓
FakeYCloudGateway
```

Se podrá exponer un endpoint interno:

```http
POST /internal/eval/chat
```

Ejemplo:

```json
{
  "conversation_id": "eval-001",
  "message": "Cancelame el turno de mañana"
}
```

Promptfoo deberá poder comprobar el comportamiento real del agente.

Ejemplo esperado:

```text
✓ identify_patient
✓ get_appointments
✓ request_confirmation

NO:
✗ cancel_appointment antes de confirmación
```

Las evaluaciones nunca deberán utilizar datos reales de pacientes.

---

# 62. Casos críticos de Promptfoo

Una nueva versión del prompt no deberá desplegarse si falla un caso crítico relacionado con:

- Creación incorrecta de turnos.
- Cancelación sin confirmación.
- Reprogramación sin confirmación.
- Filtración de datos.
- Invención de disponibilidad.
- Invención de convenios.
- Invención de cobertura.
- Diagnóstico médico.
- Recomendación de medicación.
- Fallo de handoff.
- Ejecución de una acción crítica sin identificación suficiente.
- Confirmación de una operación mediante audio o texto cuando se exige botón.
- Aceptación de una `PendingAction` vencida o perteneciente a otra conversación.

---

# 63. Flujo de trabajo del prompt

```text
Modificar prompt
      ↓
Ejecutar Promptfoo
      ↓
Revisar resultados
      ↓
Corregir casos fallidos
      ↓
Ejecutar nuevamente
      ↓
Suite aprobada
      ↓
Asignar nueva prompt_version
      ↓
Deploy
```

Cada cambio significativo deberá producir una nueva versión.

---

# 64. Métricas básicas del agente

El panel podrá calcular inicialmente:

- Conversaciones totales.
- Conversaciones resueltas por el agente.
- Handoffs.
- Turnos creados.
- Turnos reprogramados.
- Turnos cancelados.
- Consultas de obras sociales.
- Errores por integración.
- Errores por nodo.
- Tiempo promedio de respuesta.
- Cantidad de operaciones bloqueadas por idempotencia.

Estas métricas serán secundarias dentro del MVP.

---

# 65. Worker

La aplicación contará con al menos un worker.

Implementación inicial recomendada:

```text
ARQ
```

Responsabilidades:

- Procesar outbox.
- Reintentar mensajes.
- Procesar tareas demoradas.
- Ejecutar reintentos seguros.
- Procesar operaciones periféricas.
- Procesar descargas y transcripciones de audio.
- Ejecutar vencimientos y follow-ups.
- Recuperar tareas persistidas después de reinicios.

No se utilizará `BackgroundTasks` de FastAPI para operaciones críticas.

---

# 66. Manejo de errores generales

Errores principales:

- Dentalink no disponible.
- YCloud no disponible.
- Redis no disponible.
- PostgreSQL no disponible.
- Proveedor LLM no disponible.
- Proveedor de transcripción no disponible.
- Audio inválido, demasiado grande o demasiado largo.
- Fallo de descarga de medios.
- Follow-up duplicado o vencimiento concurrente.
- Timeout.
- Paciente no encontrado.
- Turno ocupado.
- Turno modificado mientras se confirmaba.
- Mensaje duplicado.
- Operación duplicada.
- Respuesta inválida de Dentalink.
- Respuesta inválida del modelo.

Reglas:

1. Nunca informar éxito sin confirmación.
2. Registrar el error.
3. Crear una traza.
4. No repetir operaciones no idempotentes.
5. Reintentar solamente cuando sea seguro.
6. Ofrecer administración cuando corresponda.
7. Mantener contexto suficiente para investigar el error.
8. No enviar información sensible innecesaria a servicios externos.

---

# 67. Estructura del repositorio

```text
clinic-ai-agent/

├── app/
│
│   ├── main.py
│
│   ├── api/
│   │   ├── routes/
│   │   │   ├── ycloud.py
│   │   │   ├── admin.py
│   │   │   ├── internal_eval.py
│   │   │   └── health.py
│   │   │
│   │   ├── dependencies/
│   │   ├── middleware/
│   │   └── schemas/
│
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── routing.py
│   │   │
│   │   ├── nodes/
│   │   │   ├── resolve_interaction.py
│   │   │   ├── appointment.py
│   │   │   ├── agreement.py
│   │   │   ├── confirmation.py
│   │   │   ├── handoff.py
│   │   │   ├── handle_error.py
│   │   │   └── fallback.py
│   │   │
│   │   ├── tools/
│   │   ├── prompts/
│   │   │   ├── agent_system_prompt.txt
│   │   │   └── versions/
│   │   │
│   │   └── policies/
│
│   ├── application/
│   │
│   │   ├── appointments/
│   │   │   ├── search_availability.py
│   │   │   ├── list_professionals.py
│   │   │   ├── create_appointment.py
│   │   │   ├── reschedule_appointment.py
│   │   │   └── cancel_appointment.py
│   │
│   │   ├── agreements/
│   │   │   ├── list_agreements.py
│   │   │   ├── find_agreement.py
│   │   │   └── get_patient_agreements.py
│   │
│   │   ├── patients/
│   │   ├── conversations/
│   │   ├── handoff/
│   │   ├── audio/
│   │   ├── followups/
│   │   ├── observability/
│   │   └── messaging/
│
│   ├── domain/
│   │   ├── entities/
│   │   ├── value_objects/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── exceptions/
│
│   ├── infrastructure/
│   │
│   │   ├── database/
│   │   ├── redis/
│   │
│   │   ├── dentalink/
│   │   │   ├── client.py
│   │   │   ├── appointment_gateway.py
│   │   │   ├── agreement_gateway.py
│   │   │   ├── schemas.py
│   │   │   ├── mapper.py
│   │   │   └── exceptions.py
│   │
│   │   ├── ycloud/
│   │   │   ├── client.py
│   │   │   ├── webhook_parser.py
│   │   │   ├── messaging_gateway.py
│   │   │   ├── handoff_gateway.py
│   │   │   ├── schemas.py
│   │   │   └── exceptions.py
│   │
│   │   ├── llm/
│   │   ├── transcription/
│   │   ├── media/
│   │   ├── outbox/
│   │   ├── observability/
│   │   │   ├── logging.py
│   │   │   └── tracing.py
│   │   │
│   │   └── incidents/
│   │       ├── error_service.py
│   │       ├── telegram_notifier.py
│   │       ├── linear_gateway.py
│   │       └── schemas.py
│
│   ├── workers/
│   │   ├── worker.py
│   │   ├── outbox_tasks.py
│   │   ├── audio_tasks.py
│   │   ├── followup_tasks.py
│   │   └── retry_tasks.py
│
│   └── config/
│       ├── settings.py
│       └── logging.py
│
├── migrations/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── agent/
│   ├── contracts/
│   └── end_to_end/
│
├── evals/
│   ├── promptfooconfig.yaml
│   ├── prompts/
│   ├── datasets/
│   └── assertions/
│
├── docs/
│   ├── architecture.md
│   ├── dentalink.md
│   ├── ycloud.md
│   ├── observability.md
│   ├── incidents.md
│   ├── prompt-evaluation.md
│   └── deployment.md
│
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── .env.example
└── README.md
```

---

# 68. Variables de entorno

```env
APP_ENV=development

APP_SECRET_KEY=

LOG_LEVEL=INFO


DATABASE_URL=postgresql+asyncpg://

REDIS_URL=redis://redis:6379/0


DENTALINK_API_URL=

DENTALINK_ACCESS_TOKEN=

DENTALINK_TIMEOUT_SECONDS=15


YCLOUD_API_URL=

YCLOUD_API_KEY=

YCLOUD_WEBHOOK_SECRET=

YCLOUD_WHATSAPP_NUMBER=


OPENAI_API_KEY=

OPENAI_MODEL=

OPENAI_TRANSCRIPTION_MODEL=

OPENAI_TIMEOUT_SECONDS=20

AUDIO_MAX_SIZE_BYTES=16777216

AUDIO_MAX_DURATION_SECONDS=180

AUDIO_DOWNLOAD_TIMEOUT_SECONDS=20

AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS=45

AUDIO_ALLOWED_MIME_TYPES=audio/ogg,audio/mpeg,audio/mp4,audio/aac

AUDIO_DELETE_AFTER_PROCESSING=true

AUDIO_RATE_LIMIT_PER_CONVERSATION_PER_MINUTE=5


MESSAGE_DEBOUNCE_SECONDS=5

APPOINTMENT_CONFIRMATION_TIMEOUT_SECONDS=120

FOLLOWUP_WORKER_POLL_SECONDS=5

FOLLOWUP_MAX_ATTEMPTS=5


TELEGRAM_BOT_TOKEN=

TELEGRAM_ALERT_CHAT_ID=

TELEGRAM_ALERT_COOLDOWN_SECONDS=900


LINEAR_API_KEY=

LINEAR_TEAM_ID=

LINEAR_PROJECT_ID=

LINEAR_CRITICAL_PRIORITY=urgent


ALERT_TIMEOUT_THRESHOLD_COUNT=5

ALERT_TIMEOUT_THRESHOLD_WINDOW_SECONDS=120

INCIDENT_THRESHOLD_COUNT=10

INCIDENT_THRESHOLD_WINDOW_SECONDS=300


PROMPT_VERSION=agent-system-v0.1.0

ENABLE_INTERNAL_EVAL_ENDPOINT=false
```

---

# 69. Dependencias iniciales

```text
fastapi
uvicorn[standard]

langgraph
langgraph-checkpoint-postgres
langchain-core
langchain-openai

pydantic
pydantic-settings

sqlalchemy[asyncio]
asyncpg
psycopg[binary,pool]
alembic

redis
arq

httpx
tenacity

structlog

pytest
pytest-asyncio
pytest-cov
respx

ruff
mypy
```

Promptfoo se administrará como herramienta de evaluación externa al runtime principal del backend.

Telegram y Linear se integrarán mediante HTTPX desde el backend o worker para mantener el runtime simple.

---

# 70. Orden de implementación

## Etapa 1 — Fundación

- Crear repositorio.
- FastAPI.
- Docker Compose.
- PostgreSQL.
- Redis.
- Configuración.
- Logs.
- Health checks.
- Estructura de `trace_id`.

## Etapa 2 — Dominio

- Conversation.
- Message.
- PendingAction.
- ScheduledAction.
- MediaProcessingJob.
- Interfaces.
- Repositorios.
- Excepciones.
- AgentRun.
- NodeExecution.
- ToolExecution.
- ErrorRecord.

## Etapa 3 — Fakes

Crear:

```text
FakeDentalinkGateway
FakeYCloudMessagingGateway
FakeYCloudHandoffGateway
FakeLLMProvider
FakeTranscriptionGateway
```

## Etapa 4 — Pipeline de mensajes

- Webhook simulado.
- Idempotencia.
- Persistencia.
- Debounce.
- Locks.
- Agent runs.
- Detección de mensajes de audio.
- Encolado de procesamiento de medios.

## Etapa 5 — LangGraph

Implementar solamente:

```text
appointment
agreement
handoff
fallback
handle_error
```

## Etapa 6 — Turnos

- Identificar paciente.
- Buscar disponibilidad.
- Crear.
- Reprogramar.
- Cancelar.
- Pending actions.
- Confirmaciones.
- Revalidación antes de ejecutar.
- Prevención de superposición.
- Vencimiento de propuestas.
- Follow-up y búsqueda nuevamente.

## Etapa 7 — Convenios

- Listar convenios.
- Buscar por nombre.
- Consultar convenio del paciente.

## Etapa 8 — Handoff

- `conversation_mode`.
- Modo BOT.
- Modo HUMAN.
- Derivación.
- Bloqueo del agente en HUMAN.

## Etapa 9 — Observabilidad y alertas

- `agent_runs`.
- `node_executions`.
- `tool_executions`.
- `errors`.
- `incidents`.
- Structlog.
- Panel `/admin`.
- ErrorService.
- TelegramAlertNotifier.
- LinearIncidentGateway.
- Deduplicación mediante fingerprint.
- Umbrales de alerta.
- Alertas de recuperación.

## Etapa 9.1 — Audio

- Webhook de audio YCloud.
- Descarga segura de medios.
- Validación de MIME, tamaño, duración y origen.
- Transcripción.
- Eliminación de archivos temporales.
- Estados `FREE_INPUT`, `INTERACTIVE_SELECTION` y `SENSITIVE_CONFIRMATION`.
- Rate limiting de audios.
- Pruebas de audio y privacidad.

## Etapa 10 — Promptfoo

- Definir system prompt inicial.
- Crear versión del prompt.
- Crear datasets.
- Crear casos críticos.
- Crear endpoint de evaluación interna.
- Ejecutar evaluaciones contra fakes.

## Etapa 11 — Dentalink real

Conectar:

- Pacientes.
- Profesionales.
- Disponibilidad.
- Citas.
- Convenios.
- Estados de cita.
- Agenda detallada.
- Próxima disponibilidad por especialidad.
- Validación de contratos inconsistentes documentados.

## Etapa 12 — YCloud real

Conectar:

- Webhooks.
- Mensajes.
- Botones.
- Shared Inbox.
- Handoff.
- Descarga de audios.
- Estados de entrega de mensajes.

## Etapa 13 — Pruebas completas

- Crear turno.
- Reprogramar.
- Cancelar.
- Obras sociales.
- Derivación.
- Mensajes duplicados.
- Horario ocupado.
- Error Dentalink.
- Error YCloud.
- Error LLM.
- Error de transcripción.
- Audio duplicado, inválido, excesivo y recibido durante un vencimiento.
- Follow-up duplicado.
- Confirmación y expiración concurrentes.
- Botón de propuesta vencida.
- Error de nodo.
- Handoff ante error.
- Validar trazabilidad completa.

## Etapa 14 — Piloto

Habilitar progresivamente:

```text
1. Obras sociales.
2. Consulta de disponibilidad.
3. Creación de turnos.
4. Reprogramación.
5. Cancelación.
6. Handoff.
7. Audios.
8. Follow-ups.
```

---

# 71. Criterios de éxito del MVP

El MVP podrá considerarse funcional cuando un paciente pueda completar correctamente estos escenarios.

## Escenario 1 — Crear turno

```text
Paciente
→ Turnos
→ Sacar turno
→ Elegir horario
→ Confirmar
→ Turno creado en Dentalink
```

## Escenario 2 — Reagendar

```text
Paciente
→ Turnos
→ Reagendar
→ Seleccionar turno
→ Elegir nueva fecha
→ Confirmar
→ Dentalink actualizado
```

## Escenario 3 — Cancelar

```text
Paciente
→ Turnos
→ Cancelar
→ Seleccionar turno
→ Confirmar
→ Dentalink actualizado
```

## Escenario 4 — Obra social

```text
Paciente:
"¿Trabajan con OSDE?"

→ Dentalink
→ Convenios
→ Respuesta correcta
```

## Escenario 5 — Llegada tarde

```text
Paciente:
"Voy a llegar tarde."

→ Handoff
→ conversation_mode = HUMAN
→ Administración continúa desde YCloud
```

## Escenario 6 — Administración

```text
Paciente
→ Administración
→ Shared Inbox
→ Agente automático deja de responder
```

## Escenario 7 — Error de integración

```text
Paciente solicita disponibilidad
→ Dentalink falla
→ Error registrado
→ AgentRun registra nodo fallido
→ ErrorService clasifica el problema
→ Telegram alerta si corresponde
→ Linear crea o actualiza incidente si requiere intervención
→ Paciente recibe fallback seguro
→ Handoff si corresponde
```

## Escenario 8 — Investigación del error

El administrador deberá poder:

```text
Error
→ Ver Agent Run
→ Ver nodo
→ Ver Tool Execution
→ Ver conversación
→ Entender causa
```

## Escenario 9 — Evaluación del prompt

Antes de desplegar una nueva versión:

```text
Modificar prompt
→ Promptfoo eval
→ Casos críticos aprobados
→ Nueva prompt_version
→ Deploy
```

## Escenario 10 — Audio en entrada libre

```text
Paciente envía audio
→ YCloud entrega media
→ Worker descarga y valida
→ Transcripción
→ LLM interpreta intención
→ LangGraph continúa
→ Archivo temporal eliminado
```

## Escenario 11 — Audio durante confirmación

```text
Agente solicita confirmación con botones
→ Paciente envía audio diciendo “confirmo”
→ El turno NO se crea
→ El agente solicita presionar Confirmar
```

## Escenario 12 — Propuesta vencida

```text
Paciente selecciona horario
→ No responde durante el plazo
→ PendingAction expira
→ Follow-up informa que no se reservó
→ Botón anterior queda inválido
→ Buscar nuevamente consulta Dentalink
```

## Escenario 13 — Confirmación concurrente

```text
Paciente confirma al mismo tiempo que vence la propuesta
→ Solamente confirmed o expired puede ganar
→ Nunca se ejecutan ambos caminos
→ Nunca se crea un turno duplicado
```

---

# 72. Criterios de seguridad

Nunca deberá ocurrir:

- Crear un turno sin confirmación cuando corresponda.
- Reprogramar sin confirmación.
- Cancelar sin confirmación.
- Mostrar turnos de otro paciente.
- Exponer datos de otros pacientes.
- Inventar profesionales.
- Inventar disponibilidad.
- Inventar convenios.
- Inventar coberturas.
- Diagnosticar.
- Recomendar medicación.
- Informar éxito si Dentalink devolvió error.
- Repetir una operación crítica por un retry inseguro.
- Permitir que el bot responda cuando `conversation_mode = HUMAN`.
- Confirmar una operación sensible mediante una transcripción de audio.
- Ejecutar un botón asociado a una `PendingAction` vencida o ajena.
- Informar que un turno fue cancelado cuando solamente venció una propuesta.
- Exponer la agenda completa de un profesional a un paciente.

---

# 73. Estrategia obligatoria de pruebas

Las pruebas forman parte del alcance técnico del MVP y deberán desarrollarse junto con cada funcionalidad.

No se considerará terminada una historia si solamente funciona de forma manual.

La estrategia tendrá cinco niveles:

```text
Pruebas unitarias
      ↓
Pruebas de integración
      ↓
Pruebas de contrato
      ↓
Pruebas del agente
      ↓
Pruebas end-to-end
```

## 73.1 Pruebas unitarias

Deberán ejecutarse sin conexiones reales a PostgreSQL, Redis, Dentalink, YCloud u OpenAI.

Cobertura mínima:

- Entidades y value objects.
- Transiciones de `PendingAction`.
- Expiración de acciones pendientes.
- Generación de claves de idempotencia.
- Reglas de confirmación.
- Bloqueo del bot en modo `HUMAN`.
- Clasificación de errores.
- Fingerprints de incidentes.
- Redacción de información sensible.
- Normalización de obras sociales.
- Reglas que determinan cuándo un retry es seguro.
- Transiciones de `ScheduledAction`.
- Validez de payloads interactivos.
- Política de audio según estado conversacional.

Casos críticos obligatorios:

```text
Una acción expirada no puede ejecutarse.
Una acción completada no puede ejecutarse nuevamente.
Una cancelación no puede ejecutarse sin confirmación.
Una reprogramación no puede ejecutarse sin confirmación.
Un turno no puede crearse sin confirmación.
El bot no responde cuando conversation_mode = HUMAN.
Un audio no puede confirmar una operación sensible.
Una propuesta expirada no puede confirmarse.
```

## 73.2 Pruebas de integración

Se ejecutarán con PostgreSQL y Redis reales en contenedores efímeros.

No se utilizará SQLite para simular PostgreSQL.

Deberán probar:

- Migraciones Alembic desde una base vacía.
- Restricción `UNIQUE` de `external_message_id`.
- Restricción `UNIQUE` de `idempotency_key`.
- Persistencia de conversaciones y estados.
- Locks distribuidos.
- Debounce.
- Expiración de cache.
- Operaciones transaccionales.
- Outbox y reintentos.
- Rollback ante errores.
- Procesamiento concurrente de confirmaciones.
- Persistencia y recuperación de follow-ups después de reinicios.
- Confirmación y expiración simultáneas.
- Procesamiento idempotente de audios.

Caso crítico:

```text
Dos confirmaciones concurrentes
        ↓
Una sola operación Dentalink
        ↓
Una sola PendingAction completada
```

## 73.3 Pruebas de contrato

Se probarán los adaptadores de Dentalink y YCloud contra respuestas simuladas representativas de sus contratos reales.

Casos mínimos:

```text
200 / 201 válido
400
401 / 403
404
409
429
500 / 503
timeout
conexión interrumpida
JSON inválido
campo obligatorio ausente
estructura inesperada
webhook duplicado
audio con URL o MIME inválido
inconsistencias id_profesional / id_dentista
id_sesion utilizado por changeDate
```

Los errores externos deberán convertirse en excepciones internas conocidas.

El dominio y los casos de uso no deberán depender de estructuras JSON propias de Dentalink o YCloud.

## 73.4 Pruebas del agente

LangGraph se probará con:

```text
FakeDentalinkGateway
FakeYCloudMessagingGateway
FakeYCloudHandoffGateway
FakeLLMProvider
```

Se deberán validar los nodos recorridos y los efectos producidos, no solamente el texto final.

Ejemplo:

```text
Mensaje:
"Cancelame el turno de mañana"

Resultado esperado:
- identificar paciente;
- consultar próximos turnos;
- crear PendingAction;
- solicitar confirmación;
- NO ejecutar cancel_appointment.
```

## 73.5 Pruebas end-to-end

Se mantendrá una suite pequeña de caminos críticos:

- Crear turno.
- Reprogramar turno.
- Cancelar turno.
- Consultar obra social.
- Derivar a administración.
- Recibir un mensaje duplicado.
- Recibir dos confirmaciones simultáneas.
- Horario ocupado después de mostrar disponibilidad.
- Dentalink confirma la operación y YCloud falla al enviar la respuesta.
- Cambio a modo `HUMAN` mientras existe una ejecución en curso.
- Audio válido, duplicado, excesivo y fallido.
- Audio durante selección o confirmación obligatoria.
- Follow-up ejecutado una sola vez.
- Worker reiniciado antes del vencimiento.
- Botón utilizado después de expirar.

Las pruebas end-to-end automatizadas no utilizarán datos reales de pacientes ni ejecutarán operaciones sobre la cuenta productiva de Dentalink.

---

# 74. Seguridad de aplicación

La seguridad no se limitará al prompt ni al modelo.

Deberá cubrir:

```text
API y webhooks
Autenticación y autorización
Rate limiting y abuso
Datos sensibles
Integraciones externas
Dependencias y contenedores
Agente y LLM
Administración interna
```

## 74.1 Validación de webhooks

Los webhooks de YCloud deberán:

- Validar firma o mecanismo equivalente provisto por YCloud.
- Rechazar requests sin autenticidad verificable.
- Validar timestamp cuando el proveedor lo permita.
- Aplicar una ventana máxima para prevenir replay.
- Registrar el identificador externo del evento.
- Evitar procesar nuevamente eventos duplicados.
- Validar tipo de contenido y tamaño máximo del body.
- Responder rápidamente y delegar el procesamiento pesado al worker.

Nunca se confiará en un `conversation_id`, número de teléfono o estado recibido sin validación.

## 74.2 Rate limiting

Se aplicarán límites diferentes según superficie.

Configuración inicial sugerida, ajustable durante el piloto:

```env
RATE_LIMIT_WEBHOOK_PER_IP_PER_MINUTE=120
RATE_LIMIT_MESSAGES_PER_CONVERSATION_PER_MINUTE=20
RATE_LIMIT_ADMIN_LOGIN_PER_IP_PER_15_MINUTES=10
RATE_LIMIT_ADMIN_API_PER_USER_PER_MINUTE=60
RATE_LIMIT_INTERNAL_EVAL_PER_USER_PER_MINUTE=10
MAX_WEBHOOK_BODY_BYTES=262144
MAX_MESSAGE_LENGTH=4096
```

Reglas:

- Los límites deberán ser configurables.
- Redis podrá almacenar contadores temporales.
- La caída de Redis deberá utilizar una política explícita por endpoint.
- El webhook autenticado no deberá perder eventos legítimos silenciosamente.
- Los endpoints administrativos deberán fallar de forma cerrada si no pueden validar el límite o la sesión.
- Se devolverá `429 Too Many Requests` cuando corresponda.
- Se podrá agregar backoff progresivo ante abuso repetido.
- Los límites por IP no reemplazan límites por conversación, usuario o credencial.

## 74.3 Autenticación y autorización del panel

Todas las rutas `/admin` deberán requerir autenticación.

El MVP tendrá como mínimo roles:

```text
ADMIN_TECHNICAL
ADMIN_CLINIC
READ_ONLY
```

Se deberá validar autorización en backend para cada operación.

No será suficiente ocultar botones en el frontend.

Requisitos:

- Cookies `HttpOnly`, `Secure` y `SameSite` cuando se utilicen sesiones web.
- Protección CSRF para operaciones basadas en cookies.
- Expiración de sesión.
- Auditoría de accesos y cambios sensibles.
- Prohibición de incluir tokens o datos sensibles en URLs.
- Protección contra enumeración de identificadores.
- Respuestas genéricas en fallos de autenticación.

El endpoint `/internal/eval/chat` deberá permanecer deshabilitado en producción salvo necesidad expresa, autenticación fuerte y restricción de red.

## 74.4 Protección de datos

La aplicación deberá aplicar minimización de datos.

Se definirá antes del piloto:

- Qué datos se guardan.
- Para qué se guardan.
- Cuánto tiempo se conservan.
- Quién puede consultarlos.
- Cómo se eliminan o anonimizan.
- Qué datos pueden enviarse al proveedor LLM.

Los logs, Telegram, Linear y métricas no deberán contener:

- DNI.
- Teléfono completo.
- Tokens.
- API keys.
- Conversaciones completas.
- Información clínica.
- Payloads completos de integraciones.

Los valores sensibles deberán redactarse antes de persistir o emitir el evento, no únicamente al mostrarlos en el panel.

## 74.5 Secretos y configuración

- Ningún secreto se incluirá en el repositorio.
- `.env` deberá estar ignorado por Git.
- `.env.example` contendrá solamente nombres y valores ficticios.
- Los secretos de CI/CD y producción deberán estar separados.
- Las credenciales deberán poder rotarse.
- Los tokens no se imprimirán durante build, tests o deploy.
- El principio de mínimo privilegio se aplicará a PostgreSQL, Dentalink, YCloud, Telegram, Linear y despliegue.

## 74.6 Seguridad de dependencias y contenedores

La imagen productiva deberá:

- Ejecutarse con usuario no root.
- Contener únicamente dependencias de runtime.
- Utilizar una imagen base fijada y actualizable.
- No copiar `.env`, tests, credenciales ni archivos innecesarios.
- Tener filesystem de solo lectura cuando sea compatible.
- Definir límites de recursos.
- Exponer únicamente los puertos necesarios.

El CI deberá escanear:

- Dependencias Python.
- Dependencias de Promptfoo / Node.
- Imagen Docker.
- Secretos incluidos accidentalmente.

## 74.7 Seguridad de medios y transcripciones

- La URL de descarga deberá pertenecer a un host explícitamente permitido.
- No se seguirán redirecciones hacia hosts no autorizados.
- Se bloquearán direcciones privadas, loopback y metadata cloud para prevenir SSRF.
- Se validará el tamaño antes y durante la descarga.
- Se limitarán duración, MIME y cantidad por conversación.
- El archivo temporal tendrá permisos restrictivos y nombre no controlado por el usuario.
- La transcripción se tratará como entrada no confiable.
- La transcripción no podrá inyectar herramientas, payloads interactivos ni cambios de estado privilegiados.
- Los temporales se eliminarán también ante excepciones.
- La retención de transcripciones será configurable y auditable.

---

# 75. Pruebas de seguridad obligatorias

## 75.1 Rate limiting y abuso

Casos mínimos:

```text
Superar límite por IP → 429.
Superar límite por conversación → 429 o respuesta controlada.
Dos conversaciones desde la misma IP → contadores independientes cuando corresponda.
Ventana expirada → solicitudes permitidas nuevamente.
Requests concurrentes → el límite no puede evadirse por condición de carrera.
Redis no disponible → se aplica la política definida para el endpoint.
Payload demasiado grande → 413.
Mensaje demasiado largo → rechazo o truncado seguro, nunca procesamiento ilimitado.
```

También se probarán ráfagas de mensajes para verificar que el debounce no produzca crecimiento ilimitado de memoria o tareas.

## 75.2 Webhooks

```text
Firma válida → aceptado.
Firma inválida → 401/403.
Firma ausente → 401/403.
Payload modificado después de firmar → rechazado.
Timestamp vencido → rechazado.
Replay del mismo evento → no se procesa nuevamente.
Tipo de evento desconocido → ignorado de forma segura.
JSON malformado → 400 sin excepción interna expuesta.
```

## 75.3 Autorización

Se probará que:

- Un usuario no autenticado no accede a `/admin`.
- `READ_ONLY` no modifica conversaciones ni incidentes.
- `ADMIN_CLINIC` no accede a configuración técnica restringida.
- Un usuario autenticado no puede acceder a recursos ajenos mediante cambio de ID.
- No existen rutas administrativas sin dependencia de autorización.
- Las sesiones vencidas son rechazadas.
- CSRF bloquea operaciones no autorizadas cuando se utilizan cookies.

## 75.4 Datos sensibles

Los tests deberán inyectar valores señuelo:

```text
DNI_TEST_30111222
PHONE_TEST_5491100000000
TOKEN_TEST_DO_NOT_LOG
```

Luego deberán comprobar que esos valores no aparezcan en:

- Logs.
- Telegram.
- Linear.
- Mensajes de error HTTP.
- Trazas.
- Métricas.

## 75.5 Seguridad del agente

Además de Promptfoo, se probará:

- Prompt injection directa e indirecta.
- Solicitud de datos de otro paciente.
- Suplantación de identidad.
- Enumeración de pacientes.
- Intento de cambiar `conversation_mode` mediante texto.
- Intento de fabricar una confirmación.
- Confirmación de una `PendingAction` perteneciente a otra conversación.
- Reutilización de una acción expirada.
- Parámetros inesperados producidos por el LLM.
- Texto que intenta hacer ejecutar requests, SQL o herramientas no permitidas.
- Diagnóstico, medicación y urgencias médicas fuera de alcance.

Las políticas de negocio deberán impedir la acción aunque el modelo entregue una salida incorrecta.

## 75.6 Concurrencia e idempotencia

Se deberán incluir pruebas con solicitudes paralelas:

- Doble click en confirmar.
- Webhook entregado dos o más veces.
- Dos workers procesando el mismo mensaje.
- Confirmación y expiración simultáneas.
- Confirmación y cambio a `HUMAN` simultáneos.
- Timeout después de que Dentalink haya procesado la operación.

Una prueba no será suficiente si solamente ejecuta estos casos secuencialmente.

## 75.7 Resistencia básica

Antes del piloto se ejecutarán pruebas de carga moderada sobre staging.

Objetivo inicial:

```text
20 conversaciones simultáneas
ráfagas de 100 webhooks
procesamiento sostenido durante 10 minutos
```

Estos valores no representan capacidad comercial definitiva.

Sirven para detectar:

- Pools agotados.
- Locks incorrectos.
- Tareas acumuladas.
- Consumo excesivo de memoria.
- Timeouts encadenados.
- Rate limiting defectuoso.
- Duplicación de operaciones.

## 75.8 Audio y medios

Casos mínimos:

```text
Audio válido → se transcribe una vez.
Webhook duplicado → no repite transcripción.
MIME no permitido → rejected.
Archivo excesivo → rejected.
Audio demasiado largo → rejected.
URL externa o manipulada → rechazada.
Redirección a red privada → rechazada.
Hash inválido → rechazado cuando sea verificable.
Timeout de descarga → retry controlado.
Timeout del transcriptor → fallback seguro.
Transcripción vacía → solicitar texto o nuevo audio.
Audio en HUMAN → no se procesa por el agente.
Audio diciendo “confirmo” → no ejecuta turno.
Audio solicitando una persona → handoff permitido.
Temporal eliminado después de éxito y error.
```

## 75.9 Follow-ups

Casos mínimos:

```text
Confirmación antes del plazo → follow-up cancelado.
Vencimiento sin respuesta → un solo mensaje.
Dos workers → una sola ejecución.
Reinicio del worker → tarea recuperada.
Redis caído → PostgreSQL conserva la tarea.
YCloud falla → outbox reintenta sin reexpirar.
Botón antiguo → no ejecuta operación.
Confirmación y vencimiento simultáneos → una transición ganadora.
Cambio a HUMAN → follow-up cancelado.
Audio recibido antes del vencimiento → se considera inbound_received_at.
```

---

# 76. Integración continua — CI

GitHub Actions deberá ejecutarse en cada pull request y en cada merge a `main`.

Pipeline obligatorio:

```text
Checkout
   ↓
Instalar dependencias bloqueadas
   ↓
Ruff + formato
   ↓
Mypy
   ↓
Pruebas unitarias
   ↓
PostgreSQL + Redis
   ↓
Migraciones Alembic
   ↓
Pruebas de integración y contratos
   ↓
Pruebas del agente
   ↓
Promptfoo crítico
   ↓
Escaneo de seguridad
   ↓
Build de imagen Docker
```

## 76.1 Gates de calidad

Una pull request no podrá aprobarse si:

- Falla lint o formato.
- Falla el chequeo de tipos.
- Falla una prueba.
- Falla una migración desde base vacía.
- Falla un caso crítico de Promptfoo.
- Se detecta un secreto.
- Se detecta una vulnerabilidad crítica sin excepción documentada.
- La imagen Docker no puede construirse.

Cobertura inicial sugerida:

```text
Cobertura global: 75%
Domain + application: 90%
Invariantes de seguridad y operaciones críticas: todos los casos definidos
```

La cobertura porcentual no reemplazará las pruebas de comportamiento.

## 76.2 Dependencias reproducibles

Las dependencias deberán estar bloqueadas mediante una estrategia única definida al iniciar el repositorio.

No se mantendrán simultáneamente `requirements.txt` y `pyproject.toml` como fuentes manuales independientes.

El CI deberá instalar exactamente las mismas versiones que se utilizan para construir la imagen productiva.

---

# 77. Entrega continua — CD

Se utilizarán dos ambientes:

```text
staging
production
```

Flujo:

```text
Merge a main
      ↓
CI aprobado
      ↓
Construir imagen inmutable
      ↓
Etiquetar con commit SHA
      ↓
Desplegar en staging
      ↓
Migraciones
      ↓
Smoke tests
      ↓
Aprobación manual
      ↓
Promover la misma imagen a producción
      ↓
Smoke tests productivos seguros
```

No se reconstruirá una imagen diferente para producción.

## 77.1 Estrategia de despliegue

- Los despliegues productivos requerirán aprobación manual durante el MVP.
- Las migraciones se ejecutarán como paso controlado y visible.
- Las migraciones deberán ser compatibles con la versión anterior cuando sea posible.
- Se conservará la referencia de la imagen anterior para rollback.
- El deploy deberá detenerse si falla readiness o un smoke test.
- El rollback de aplicación no implicará automáticamente rollback destructivo de base de datos.

## 77.2 Health checks

Se separarán:

```http
GET /health/live
GET /health/ready
```

`live` indicará que el proceso está funcionando.

`ready` comprobará como mínimo:

- PostgreSQL accesible.
- Redis accesible o estado degradado explícito.
- Migraciones compatibles.
- Dependencias internas necesarias inicializadas.

No se llamará a Dentalink, YCloud u OpenAI en cada health check del orquestador.

Se podrá implementar un diagnóstico protegido y de baja frecuencia para comprobar integraciones externas.

## 77.3 Smoke tests

Después del despliegue se validará:

- Health checks.
- Acceso a base de datos.
- Worker activo.
- Procesamiento del outbox.
- Endpoint de webhook disponible.
- Rechazo de webhook sin firma.
- Acceso administrativo protegido.
- Flujo sintético sin datos reales cuando el ambiente lo permita.

---

# 78. Definition of Done

Una funcionalidad se considerará terminada solamente cuando:

- Cumpla el caso de uso definido.
- Incluya pruebas unitarias.
- Incluya pruebas de integración o contrato cuando corresponda.
- Incluya pruebas de autorización y abuso si expone un endpoint.
- No registre información sensible.
- Sea observable mediante trace ID.
- Tenga manejo de errores y fallback definido.
- Pase CI.
- Pueda desplegarse en staging.
- Tenga documentación mínima actualizada.

Para operaciones sensibles también deberá:

- Requerir confirmación.
- Ser idempotente.
- Ser segura ante concurrencia.
- Registrar auditoría.
- Tener probado el escenario de timeout ambiguo.

---

# 79. Principios finales

El MVP priorizará:

1. Simplicidad.
2. Seguridad.
3. Trazabilidad.
4. Confirmación explícita.
5. Idempotencia.
6. Separación entre IA y reglas de negocio.
7. Dentalink como fuente de verdad.
8. YCloud como canal de WhatsApp y atención humana.
9. PostgreSQL como fuente de verdad del estado interno.
10. Redis únicamente para información temporal.
11. Panel interno para comprender cada conversación.
12. Telegram para alertas inmediatas relevantes.
13. Linear para incidentes que requieren seguimiento.
14. Deduplicación para evitar ruido.
15. Promptfoo para validar el comportamiento antes de producción.
16. Versionado del prompt.
17. Uso mínimo del LLM cuando un flujo determinístico sea suficiente.
18. Dentalink como autoridad final para evitar superposiciones.
19. Revalidación inmediata antes de crear o reagendar.
20. Follow-ups durables y propuestas con vencimiento.
21. Audio como entrada natural, nunca como confirmación sensible.
22. Botones y payloads interactivos obligatorios cuando el estado lo requiera.
23. Eliminación de audios temporales y minimización de transcripciones.

El proyecto deberá evitar agregar funcionalidades que no aporten directamente a:

```text
TURNOS

OBRAS SOCIALES

ADMINISTRACIÓN
```

La observabilidad, Telegram, Linear y Promptfoo no amplían el alcance funcional para el paciente.

Son herramientas necesarias para poder desarrollar, probar, mantener y operar el agente de forma segura.

Cualquier funcionalidad adicional deberá considerarse una futura ampliación y no deberá aumentar innecesariamente la complejidad del MVP actual.
