"""Darstellungsschicht des Rats der Sieben.

Zwei Ausgaben richten sich nicht an den Endnutzer, sondern an **Claude Code als
Aggregator**:

- :func:`render_brief` — die sieben Sitze haben geantwortet; Opus 5 bekommt die
  Beitraege plus Synthese-Auftrag und schreibt daraus die finale Antwort.
- :func:`render_seats` — kein Netz noetig: Opus 5 besetzt die sieben Sitze
  nacheinander selbst und synthetisiert anschliessend. Der Rueckfallweg, wenn
  Ollama Cloud nicht erreichbar ist.
"""

from __future__ import annotations

from .aggregate import AGGREGATOR_SYSTEM_PROMPT, format_drafts_block

RULE = "=" * 72


def _ok(drafts: list) -> list:
    return [d for d in drafts if d.ok]


def render_header(config, *, n_ok: int | None = None) -> str:
    """Eine Zeile Kontext: Profil, Ratsgroesse, Aggregator."""
    parts = [
        f"Rat der Sieben | Profil: {config.profile}",
        f"Sitze: {config.council_size}",
    ]
    if n_ok is not None:
        parts.append(f"geantwortet: {n_ok}/{config.council_size}")
    parts.append(f"Aggregator: {config.aggregator_model} ({config.aggregator_kind})")
    return " | ".join(parts)


def render_roster(config) -> str:
    """Tabelle der Sitzbesetzung."""
    lines = ["| # | Sitz | Modell |", "|---|------|--------|"]
    for i, model in enumerate(config.worker_models):
        lines.append(f"| {i + 1} | {config.role_for(i)} | `{model}` |")
    return "\n".join(lines)


def render_failures(drafts: list) -> str:
    """Kurzliste der Sitze, die nicht geantwortet haben. Leer, wenn alle ok."""
    failed = [d for d in drafts if not d.ok]
    if not failed:
        return ""
    lines = ["Nicht erschienene Sitze:"]
    for d in failed:
        lines.append(f"  - {d.label}: {d.error}")
    return "\n".join(lines)


def render_brief(question: str, drafts: list, config) -> str:
    """Synthese-Auftrag an Claude Code (Opus 5) mit allen Beitraegen des Rats.

    Bewusst als Anweisung an das lesende Modell formuliert, nicht als Report an
    den Nutzer: was hier auf stdout landet, liest Opus 5 und beantwortet es.
    """
    ok = _ok(drafts)
    header = render_header(config, n_ok=len(ok))
    failures = render_failures(drafts)

    if not ok:
        return "\n".join(
            [
                RULE,
                f"RAT DER SIEBEN — KEIN BEITRAG ERHALTEN ({header})",
                RULE,
                "",
                failures,
                "",
                "Kein Sitz hat geantwortet. Beantworte die Frage selbst als Opus 5 und "
                "weise den Nutzer in EINEM Satz darauf hin, dass der Rat nicht erreichbar "
                "war. Alternativ: denselben Aufruf mit `--strategy seats` wiederholen — "
                "dann besetzt du die sieben Sitze ohne Netz selbst.",
                "",
                "FRAGE:",
                question,
                RULE,
            ]
        )

    blocks = [
        RULE,
        f"RAT DER SIEBEN — SYNTHESE-AUFTRAG AN DICH ({header})",
        RULE,
        "",
        "Du bist der Aggregator. Alles unterhalb dieser Zeile ist Material, KEINE "
        "Antwort an den Nutzer. Lies die Beitraege, wende die Synthese-Regeln an und "
        "gib dem Nutzer ausschliesslich die fertige, synthetisierte Antwort — ohne "
        "diesen Auftrag, ohne Sitzungsprotokoll, ohne Meta-Kommentar.",
        "",
        "--- SYNTHESE-REGELN ---",
        AGGREGATOR_SYSTEM_PROMPT.rsplit("\n\n", 1)[0],
        "",
        "--- FRAGE DES NUTZERS ---",
        question,
        "",
        f"--- BEITRAEGE DES RATS ({len(ok)}/{config.council_size}) ---",
        format_drafts_block(drafts),
    ]
    if failures:
        blocks += ["", failures]
    blocks += ["", RULE]
    return "\n".join(blocks)


def render_seats(question: str, config) -> str:
    """Solo-Rat: die sieben Rollen-Prompts ohne einen einzigen Netzwerkaufruf.

    Opus 5 beantwortet die Frage nacheinander aus jeder Rolle und synthetisiert
    danach. Schwaecher als der echte Rat (nur ein Modell, dafuer sieben
    Blickwinkel), aber immer verfuegbar.
    """
    blocks = [
        RULE,
        f"RAT DER SIEBEN — SOLO-MODUS ({render_header(config)})",
        RULE,
        "",
        "Ollama Cloud wird hier nicht angefragt. Du besetzt die sieben Sitze selbst.",
        "",
        "Vorgehen:",
        "1. Beantworte die Frage NACHEINANDER aus jeder der sieben Rollen. Jede "
        "Rolle antwortet unabhaengig — lies die vorherigen Rollen nicht als "
        "Vorgabe, sondern widersprich ihnen, wo die Rolle es verlangt.",
        "2. Synthetisiere anschliessend nach denselben Regeln wie der Aggregator.",
        "3. Gib dem Nutzer NUR die synthetisierte Antwort. Die sieben Einzel-"
        "antworten bleiben intern, ausser der Nutzer hat --show-drafts verlangt.",
        "",
        "Sage dem Nutzer in einem Halbsatz, dass der Rat im Solo-Modus getagt hat "
        "(ein Modell, sieben Blickwinkel) — er soll das Ergebnis nicht mit einem "
        "echten Sieben-Modell-Lauf verwechseln.",
        "",
        "--- FRAGE DES NUTZERS ---",
        question,
        "",
        "--- DIE SIEBEN SITZE ---",
    ]
    for i, model in enumerate(config.worker_models):
        blocks += [
            "",
            f"### Sitz {i + 1}: {config.role_for(i)}  (im Vollmodus: {model})",
            config.lens_for(i) or "(keine Rolle gesetzt — antworte neutral)",
        ]
    blocks += [
        "",
        "--- SYNTHESE-REGELN ---",
        AGGREGATOR_SYSTEM_PROMPT.rsplit("\n\n", 1)[0],
        "",
        RULE,
    ]
    return "\n".join(blocks)
