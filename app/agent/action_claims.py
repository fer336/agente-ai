"""Deterministic guard: an LLM-worded reply must never claim an action already ran.

Confirming, cancelling and rescheduling only happen when the patient taps the
confirmation button and the gateway call succeeds. Everything the model words before
that (reminders, proposals, free-text answers) must not say or imply otherwise, so this
backstop sits behind the prompt rule ("never trust the prompt alone", PRD.md §75.5).
"""

import re

#: Safe text for a free-text answer that offers a diagnosis, likely cause or treatment.
SAFE_DIAGNOSIS_ANSWER = (
    "No puedo darte un diagnóstico por acá: lo tiene que evaluar un profesional. "
    "¿Querés sacar un turno para que te revisen?"
)

#: Safe text for a free-text answer (question/fallback nodes) that claimed an action ran.
SAFE_ACTION_CLAIM_ANSWER = (
    "Todavía no se hizo ningún cambio en tus turnos: se confirman o se cancelan solo "
    "tocando los botones ✅ Confirmar / ❌ Cancelar del paso correspondiente."
)

#: First-person present ("te lo confirmo") and past ("ya lo cancelé") of the actions.
_FIRST_PERSON_PRESENT = r"(?:confirmo|cancelo|reprogramo|reservo|agendo|anoto)"
_FIRST_PERSON_PAST = r"(?:confirmé|cancelé|reprogramé|reservé|agendé|anoté)"
_PARTICIPLE = r"(?:confirmad|cancelad|reprogramad|agendad|anotad|reservad)[oa]s?"

_CLAIM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # "te lo confirmo", "te la cancelo", "ahí te lo reprogramo"
        rf"\bte\s+(?:lo|la|los|las)\s+(?:{_FIRST_PERSON_PRESENT}|{_FIRST_PERSON_PAST}"
        r"|dejo\s+" + _PARTICIPLE + r")\b",
        # "te confirmo el turno", "te reservo el de las 10" — but "te confirmo que atendemos"
        # is plain information.
        rf"\bte\s+{_FIRST_PERSON_PRESENT}\b(?!\s+(?:que|si|cu[aá]l|cu[aá]nto|cu[aá]ndo|el\s+dato)\b)",
        # "ya te anoté", "ya lo cancelé", "ya confirmé", "he confirmado"
        rf"\bya\s+(?:te\s+)?(?:(?:lo|la)\s+)?{_FIRST_PERSON_PAST}\b",
        rf"\b{_FIRST_PERSON_PAST}\s+(?:tu|el|ese|su|la)\s+(?:turno|cita|consulta|reserva)\b",
        r"\bhe\s+(?:confirmad|cancelad|reprogramad|agendad|anotad|reservad)o\b",
        # "confirmamos tu turno", "cancelamos el turno"
        r"\b(?:confirmamos|cancelamos|reprogramamos|agendamos|anotamos|reservamos)\s+"
        r"(?:tu|el|ese|su|la)\s+(?:turno|cita|consulta|reserva)\b",
        # "listo, turno confirmado", "Listo! Quedó cancelado"
        rf"\blist[oa]\b[^.!?\n]{{0,40}}\b{_PARTICIPLE}\b",
        # "quedó confirmado", "ya está cancelado", "queda reprogramado"
        rf"\b(?:qued[óo]|queda|quedaron|est[aá]|fue|ya\s+est[aá])\s+(?:ya\s+)?{_PARTICIPLE}\b",
        # "nos vemos el lunes", "te esperamos mañana"
        r"\bnos\s+vemos\s+(?:el|este|esta|la|ma[ñn]ana|hoy|pasado)\b",
        r"\bte\s+esperamos\s+(?:el|este|esta|ma[ñn]ana|hoy|pasado)\b",
        # Present/future promises to act right away: "ahí lo cancelo", "lo agendo", "te lo
        # reprogramo". Only the indicative counts ("querés que lo cancele?" is a question).
        r"\b(?:te\s+)?(?:lo|la)\s+(?:cancelo|reprogramo|reagendo|agendo|reservo|anoto|confirmo)\b",
        # "cancelo el turno", "agendo tu cita"
        r"\b(?:cancelo|reprogramo|reagendo|agendo|reservo|anoto|confirmo)\s+"
        r"(?:tu|el|ese|su|la)\s+(?:turno|cita|consulta|reserva)\b",
        # "procedo a cancelar", "procedemos a agendar"
        r"\bproced(?:o|emos)\s+a\s+(?:cancelar|reagendar|agendar|reprogramar|confirmar|reservar"
        r"|anotar)(?:l[oa]s?)?\b",
        # "ya lo hago", "lo hago ahora", "listo, lo hago"
        r"\bya\s+lo\s+hago\b",
        r"\blo\s+hago\s+(?:ya|ahora|enseguida)\b",
        r"\blist[oa][,!]?\s+lo\s+hago\b",
    )
)

#: Words that make a claim conditional or negated. "no"/"todavía"/"aún" only count right
#: before the verb ("todavía no está confirmado"); a distant "no" ("No te preocupes, ahí te
#: lo cancelo") must not hide a claim. Conditional clauses count anywhere earlier in the
#: sentence ("cuando toques Confirmar, queda confirmado", "si tocás Confirmar, te lo confirmo").
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|todav[ií]a|a[uú]n)\s+(?:\w+\s+)?$|\bas[ií]\s+$", re.IGNORECASE
)
_CONDITION_BEFORE = re.compile(
    r"\b(?:cuando|una\s+vez|hasta\s+que)\b"
    # A real conditional clause ("si tocás", "si querés", "apenas toques"), never a bare
    # affirmative "si"/"sí" ("Dale si, te lo confirmo").
    r"|\bsi\s+(?:me\s+)?(?:toc[aá]s|quer[eé]s|confirm[aá]s|apret[aá]s|presion[aá]s|"
    r"eleg[ií]s|decid[ií]s|prefer[ií]s|necesit[aá]s)\b"
    r"|\bapenas\s+(?:toqu?[eé]s|confirm[eé]s|apriet[eé]s|presion[eé]s)\b"
    r"|\bpara\s+que\s+(?:te|se|lo|la)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"[.!?\n]")


def _is_hedged(text: str, match_start: int) -> bool:
    sentence_start = 0
    for boundary in _SENTENCE_BREAK.finditer(text, 0, match_start):
        sentence_start = boundary.end()
    prefix = text[sentence_start:match_start]
    return bool(_NEGATION_BEFORE.search(prefix) or _CONDITION_BEFORE.search(prefix))


def claims_executed_action(text: str) -> bool:
    """True when `text` says or implies an appointment action was already carried out.

    Only meant for replies produced while no action ran in the turn; a genuine
    post-execution message must bypass it explicitly rather than be guessed at.
    """
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_hedged(text, match.start()):
                return True
    return False


_CONDITION = (
    r"(?:caries|infecci[oó]n(?:es)?|absceso|gingivitis|periodontitis|pulpitis|pericoronitis"
    r"|fractura|fisura|sensibilidad|hipersensibilidad|bruxismo|sarro|necrosis|fl[eé]m[oó]n"
    r"|neuralgia|desgaste)"
)
_MEDICATION = (
    r"(?:ibuprofeno|paracetamol|amoxicilina|antibi[oó]tico|analg[eé]sico|antiinflamatorio"
    r"|aspirina|diclofenac|ketorolac)"
)
_SAME_SENTENCE = r"[^.!?\n]"

_DIAGNOSIS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # "podría tratarse de una caries", "puede ser una fractura", "podría ser bruxismo"
        rf"\b(?:podr[ií]a|puede|pueden)\s+(?:ser|tratarse)\b{_SAME_SENTENCE}{{0,30}}?\b{_CONDITION}\b",
        # "parece una infección", "parecería una caries"
        rf"\bparec(?:e|er[ií]a)\b{_SAME_SENTENCE}{{0,25}}?\b{_CONDITION}\b",
        # "probablemente sea un absceso", "seguramente tengas gingivitis", "tal vez es sarro"
        rf"\b(?:probablemente|seguramente|posiblemente|quiz[aá]s?|tal\s+vez)\b"
        rf"{_SAME_SENTENCE}{{0,30}}?\b{_CONDITION}\b",
        # "es una caries", "sería una infección"
        rf"\b(?:es|ser|sea|ser[ií]a)\s+(?:una?|la|el)\s+{_CONDITION}\b",
        # "suena a una pulpitis", "se trata de una infección", "tengas caries"
        rf"\b(?:suena\s+a|se\s+trata\s+de|tengas?|tenga[sn]?)\b{_SAME_SENTENCE}{{0,20}}?\b{_CONDITION}\b",
        # "es síntoma de caries", "indica una infección", "compatible con pulpitis"
        rf"\b(?:s[ií]ntoma\s+de|signo\s+de|se[ñn]al\s+de|indica|sugiere|compatible\s+con)\b"
        rf"{_SAME_SENTENCE}{{0,20}}?\b{_CONDITION}\b",
        # "tomá ibuprofeno", "te recomiendo un antibiótico"
        rf"\b(?:tom[aá]|tomar|te\s+recomiendo|recomiendo)\b{_SAME_SENTENCE}{{0,40}}?\b{_MEDICATION}\b",
    )
)


def offers_diagnosis(text: str) -> bool:
    """True when `text` suggests a diagnosis, a likely cause or a treatment for symptoms.

    Deliberately narrow: a condition word only counts next to diagnostic phrasing ("podría
    tratarse de una caries", "es una infección", "tomá ibuprofeno"), so "tenemos turnos para
    caries" still passes. Educational statements that define a condition ("la caries es una
    infección bacteriana") are flagged too: the clinic prefers a professional answer.
    """
    return any(pattern.search(text) for pattern in _DIAGNOSIS_PATTERNS)


def guard_free_text_answer(text: str) -> str:
    """Returns `text`, or a safe static answer when it claims an action already ran or
    offers a diagnosis.

    For the model's free-text answers (`understand()`'s `answer`), which never execute
    anything (a claim there is always false) and never diagnose.
    """
    if offers_diagnosis(text):
        return SAFE_DIAGNOSIS_ANSWER
    if claims_executed_action(text):
        return SAFE_ACTION_CLAIM_ANSWER
    return text
