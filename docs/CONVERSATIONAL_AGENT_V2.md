# Conversational Agent V2 — Smiling Pilar

## Objetivo

Evolucionar el agente existente desde una máquina de estados lineal a una arquitectura conversacional con workflows operacionales navegables. No se rehace el proyecto desde cero: se preservan YCloud, Dentalink, memoria, Redis, PostgreSQL, checkpointer, PendingAction, WhatsApp Flows, handoff, tracing y garantías de seguridad.

## Regla central

El grafo debe poder **avanzar, quedarse, retroceder, reparar y desviarse temporalmente sin perder información válida**.

- Entrar a un nodo no significa necesariamente preguntarle algo al paciente.
- El nodo inspecciona primero el estado.
- Si ya tiene lo necesario, continúa automáticamente.
- Si falta información, pide únicamente lo faltante y permanece/vuelve al nodo responsable.
- Navegar hacia atrás no resetea todo el workflow.
- Los datos se invalidan por dependencia.

### Dependencias del booking

`service/specialty -> provider_group -> professional -> availability -> slot -> confirmation`

Ejemplos:

- cambiar horario: conservar paciente, servicio/grupo y profesional; invalidar disponibilidad y slot;
- cambiar profesional: conservar paciente y servicio/grupo; invalidar profesional, disponibilidad y slot;
- cambiar servicio/especialidad: conservar identidad del paciente; recalcular el resto;
- volver para completar DNI/nombre: conservar todas las selecciones operacionales que sigan siendo válidas.

## Tipos de transición

- **normal**: siguiente nodo;
- **repair**: falta o se invalidó una precondición, volver al nodo que la resuelve;
- **navigation**: el paciente decide cambiar una selección previa;
- **temporary**: consulta lateral (OSDE, ubicación, pregunta, especialidades) y luego reanudar;
- **replace**: empieza otra operación y reemplaza el workflow actual;
- **terminate**: handoff o salida explícita.

## Router global

Un `stage` activo es un cursor operacional, no una obligación de interpretar todo como turno. Los payloads globales tienen prioridad desde cualquier estado. Los botones internos de un stage siguen siendo deterministas y nunca se reclasifican con el LLM.

El router recibe mensaje, payload, mensajes recientes, memoria, workflow activo, stage y datos relevantes. El LLM interpreta lenguaje y menciones; no genera IDs ni ejecuta acciones.

## Appointment subgraph objetivo

```text
resolve_operation
      |
resolve_service
      |
resolve_provider_group
      |
choose_professional <---------------------+
      |                                   |
search_availability -- sin turnos --------+
      |
choose_slot -- cambiar profesional -------+
   |  |
   |  +-- cambiar servicio -> resolve_service
   |
identify_patient -- falta dato -> identify_patient
      |
confirm
  |   |   |
  |   |   +-- cambiar profesional -> choose_professional
  |   +------ cambiar horario -> search_availability
  +---------- slot inválido -> search_availability
      |
execute
```

La extracción desde `appointment.py` será progresiva. No se sacrifican PendingAction, idempotencia ni revalidación por tener un dibujo más lindo del grafo.

## Interrupciones temporales

Ejemplo: `stage=awaiting_slot_selection` y el paciente pregunta `aceptan OSDE?`.

1. router -> `insurance`, `interruption=temporary`;
2. se responde con datos reales;
3. el stage de turno no se borra;
4. el siguiente mensaje puede continuar seleccionando el horario.

Una pregunta lateral no debe anexar automáticamente el menú Sacar/Reagendar/Cancelar.

## Navegación y persistencia

El paciente puede decir `quiero cambiar de profesional`, `volver a especialidades` o `buscar otro horario`. Esa intención se representa como `navigation_target` y el workflow invalida solamente la cadena dependiente. Identidad y datos independientes quedan guardados.

Las confirmaciones sensibles son la excepción: texto/audio nunca confirma crear, cancelar o reprogramar. En confirmación se mantienen los botones deterministas y la escritura se ejecuta solo después de validar el PendingAction.

## Modelo clínico — fase posterior

Separar prestaciones comerciales de especialidades Dentalink.

Menú objetivo:

- Agendar una cita
- Tratamientos y precios
- Alineadores
- Reprogramar mi cita
- Cancelar mi cita
- Ver mi cita
- Obras sociales
- Cómo llegar
- Hablar con un asesor

Prestaciones iniciales: Blanqueamiento, Limpieza particular, Consulta particular, Extracción particular y Alineadores. No cargar precios hasta recibir valores confirmados.

Grupos iniciales: `GENERAL` y `ORTHODONTICS`, con IDs reales de profesionales Dentalink y soporte para excepciones por profesional específico (por ejemplo carillas).

Dentalink sigue siendo la fuente de verdad para profesionales, pacientes, turnos, disponibilidad y escrituras. El catálogo propio determina cómo la clínica modela comercialmente sus servicios.

## Fases

### PR 1 — arquitectura conversacional base

- router global;
- contexto real en `understand`;
- interrupciones informativas temporales;
- nodo de pregunta sin menú obligatorio;
- nodo determinista de ubicación;
- estado de navegación;
- invalidación por dependencia;
- reparación básica de estados faltantes;
- bug de `response_list`;
- tests.

### PR 2 — appointment subgraph

Extraer progresivamente nodos reales: operación, servicio, profesional, disponibilidad, slot, identificación, confirmación y ejecución. Agregar ciclos/guards explícitos.

### PR 3 — catálogo clínico

`ClinicService`, grupos GENERAL/ORTHODONTICS, menú nuevo, tratamientos/precios y alineadores.

### PR 4 — booking por servicio

`ClinicService -> provider group -> profesionales Dentalink -> agenda real`.

## Seguridad

El LLM nunca es fuente de verdad para precio, profesional, ID, disponibilidad, turno, cobertura, dirección o identidad. Puede clasificar, extraer menciones, entender referencias y redactar. Las operaciones sensibles siguen siendo deterministas.
