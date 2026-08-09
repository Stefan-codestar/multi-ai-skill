from __future__ import annotations

from typing import Any


# Stabiler Marker im System-Prompt: daran erkennen Tests und Provider-Wrapper
# einen Synthese-Call und unterscheiden ihn von einem Sitz-Call.
SYNTH_MARKER = "Beitraege des Rats"

AGGREGATOR_SYSTEM_PROMPT = (
    "Du bist der Aggregator im RAT DER SIEBEN. Sieben Modelle unterschiedlicher "
    "Herkunft haben dieselbe Frage aus je einer eigenen Rolle beantwortet: "
    "Analytiker, Ingenieur, Skeptiker, Stratege, Pragmatiker, Erklaerer, Querdenker.\n\n"
    "Deine Aufgabe ist nicht, die Beitraege aneinanderzureihen, sondern EINE bessere "
    "Antwort daraus zu bauen. Halte dich an diese Regeln:\n\n"
    "1. Pruefe jeden Beitrag kritisch — einzelne koennen falsch, veraltet oder "
    "voreingenommen sein. Mehrheit ist kein Wahrheitsbeweis.\n"
    "2. Wo die Beitraege sich WIDERSPRECHEN, entscheide begruendet und benenne den "
    "Dissens kurz, statt ihn zu verschweigen.\n"
    "3. Nimm die Einwaende des Skeptikers ernst, aber uebernimm sie nur, wenn sie "
    "belegt sind.\n"
    "4. Uebernimm einen Vorschlag des Querdenkers nur, wenn er tatsaechlich traegt.\n"
    "5. Antworte in der Sprache der Frage, strukturiert und ohne Fuellwerk. "
    "Erwaehne die Rollen nur, wo es der Klarheit dient — der Nutzer will eine "
    "Antwort, keinen Sitzungsbericht.\n\n"
    f"{SYNTH_MARKER} der Sieben:"
)


def _ok(drafts: list) -> list:
    return [d for d in drafts if d.ok]


def _label(d, fallback_index: int) -> str:
    role = getattr(d, "role", "") or ""
    return f"{role} ({d.model})" if role else f"Beitrag {fallback_index}"


def concat_drafts(drafts: list) -> str:
    """Alle erfolgreichen Beitraege untereinander, ohne Synthese."""
    blocks = []
    for i, d in enumerate(_ok(drafts), start=1):
        blocks.append(f"## {_label(d, i)}\n\n{d.content}")
    return "\n\n---\n\n".join(blocks)


def format_drafts_block(drafts: list) -> str:
    """Nummerierte Beitraege mit Rollen-Label — der Kern des Synthese-Prompts."""
    return "\n\n".join(
        f"### {i}. {_label(d, i)}\n{d.content}"
        for i, d in enumerate(_ok(drafts), start=1)
    )


def build_synthesis_messages(question: str, drafts: list) -> list[dict[str, str]]:
    """Baut die Nachrichten fuer den Aggregator.

    Wird von :func:`synthesize`, :func:`synthesize_stream` und vom
    Brief-Modus (Claude Code als Aggregator) gemeinsam genutzt, damit alle drei
    Wege denselben Auftrag stellen.
    """
    system_content = AGGREGATOR_SYSTEM_PROMPT + "\n\n" + format_drafts_block(drafts)
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]


def synthesize(
    provider,
    question: str,
    drafts: list,
    *,
    aggregator_model: str = "glm-5.2",
    max_tokens: int = 8192,
    temperature: float = 0.3,
    extra_body: dict[str, Any] | None = None,
) -> str:
    return provider.complete(
        aggregator_model,
        build_synthesis_messages(question, drafts),
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )


def synthesize_stream(
    provider,
    question: str,
    drafts: list,
    *,
    aggregator_model: str = "glm-5.2",
    max_tokens: int = 8192,
    temperature: float = 0.3,
    extra_body: dict[str, Any] | None = None,
):
    """Wie :func:`synthesize`, streamt die Antwort aber chunkweise.

    Yieldt str-Chunks; der Aufrufer ist fuer die Ausgabe verantwortlich.
    """
    yield from provider.stream_complete(
        aggregator_model,
        build_synthesis_messages(question, drafts),
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
