"""Selbstbewertung: der Rat der Sieben beurteilt den Rat der Sieben.

Baut aus dem Repository selbst die Frage, die dem Rat vorgelegt wird. Damit ist
die Abnahme des Skills ein Lauf des Skills — faellt der Rat aus, faellt der Test
auf, und die Bewertung kommt aus sieben unabhaengigen Blickwinkeln statt aus dem
Kopf des Autors.
"""

from __future__ import annotations

import os

from .profiles import PROFILES, diversity_report

# Dateien, die dem Rat im Volltext vorgelegt werden. Reihenfolge = Lesereihenfolge.
CORE_FILES = [
    "SKILL.md",
    "multiai/profiles.py",
    "multiai/config.py",
    "multiai/pipeline.py",
    "multiai/council.py",
]

# Obergrenze pro Datei, damit der Prompt in jedes Kontextfenster passt.
MAX_CHARS_PER_FILE = 12000

EVAL_AXES = [
    "**Ratsdesign** — Sind sieben Sitze mit je eigener Rolle und eigenem Modell "
    "eine echte Verbesserung gegenueber drei Modellen ohne Rollen, oder erzeugen "
    "die Rollen-Prompts nur Scheindiversitaet?",
    "**Aggregator-Wahl** — Opus 5 in-process unter Claude Code, glm-5.2 per HTTP "
    "auf dem VPS. Ist die Trennung sinnvoll? Welche Risiken entstehen daraus, "
    "dass der Aggregator unter Claude Code kein Programmcode, sondern eine "
    "Instruktion an das lesende Modell ist?",
    "**Diversitaet** — Die Sitze verteilen sich auf sieben Labs und drei Laender, "
    "mit Uebergewicht auf chinesischen Laboren. Mindert das den Wert des Rats, "
    "und was waere die bessere Verteilung im gegebenen Katalog?",
    "**Robustheit** — Quorum, Ausfall einzelner Sitze, Parallelitaetsgrenze von "
    "drei gleichzeitigen Modellen auf Ollama Cloud Pro. Wo bricht das Design?",
    "**Latenz und Kosten** — Sieben Sitze mit hohem Reasoning-Budget bei drei "
    "gleichzeitigen Slots. Lohnt der Aufwand gegenueber drei Sitzen, und ab "
    "welcher Fragenart nicht mehr?",
    "**Ausloesung** — Wann soll der Skill automatisch anspringen? Ist das "
    "Kriterium in SKILL.md scharf genug, um weder zu haeufig noch zu selten "
    "auszuloesen?",
    "**Schwachstellen** — Was ist der groesste konkrete Fehler im vorliegenden "
    "Entwurf?",
]


def _repo_root(start: str | None = None) -> str:
    """Wurzel des Skill-Repos — das Verzeichnis ueber dem Paket."""
    here = start or os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def _read_capped(path: str, cap: int = MAX_CHARS_PER_FILE) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if len(text) > cap:
        text = text[:cap] + f"\n... [gekuerzt, {len(text) - cap} Zeichen ausgelassen]"
    return text


def _profile_overview() -> str:
    lines = []
    for name, profile in sorted(PROFILES.items()):
        lines.append(f"### Profil `{name}`")
        lines.append(profile.description)
        lines.append("")
        lines.append(diversity_report(profile))
        lines.append("")
        lines.append("| # | Sitz | Modell | Lab | Land |")
        lines.append("|---|------|--------|-----|------|")
        for i, s in enumerate(profile.seats, start=1):
            lines.append(f"| {i} | {s.role} | `{s.model}` | {s.lab} | {s.country} |")
        lines.append("")
    return "\n".join(lines)


def build_self_eval_question(repo_root: str | None = None,
                             files: list[str] | None = None) -> str:
    """Setzt die Selbstbewertungs-Frage aus Profilen und Quelltext zusammen."""
    root = repo_root or _repo_root()
    wanted = files if files is not None else CORE_FILES

    parts = [
        "Bewerte den folgenden Skill kritisch und mache konkrete "
        "Verbesserungsvorschlaege.",
        "",
        "Der Skill heisst **Rat der Sieben**. Er stellt eine Frage parallel an "
        "sieben Sprachmodelle unterschiedlicher Herkunft, die jeweils eine "
        "festgelegte Rolle einnehmen, und laesst ein achtes Modell die Beitraege "
        "zu einer Antwort synthetisieren. Du selbst bist gerade Teil dieses Rats — "
        "bewerte trotzdem streng und ohne Wohlwollen gegenueber dem eigenen Aufbau.",
        "",
        "## Zu bewertende Punkte",
        "",
    ]
    parts += [f"{i}. {axis}" for i, axis in enumerate(EVAL_AXES, start=1)]
    parts += [
        "",
        "## Erwartete Antwortform",
        "",
        "Zuerst ein Urteil in zwei bis drei Saetzen. Danach die konkreten "
        "Verbesserungsvorschlaege, nach Wirkung sortiert, jeweils mit "
        "Begruendung und geschaetztem Aufwand. Vage Empfehlungen ('mehr Tests', "
        "'bessere Doku') sind wertlos — benenne Datei, Stelle und Aenderung.",
        "",
        "## Die zwei Umgebungsprofile",
        "",
        _profile_overview(),
        "## Quelltext",
        "",
    ]

    for rel in wanted:
        text = _read_capped(os.path.join(root, rel))
        if text is None:
            continue
        lang = "markdown" if rel.endswith(".md") else "python"
        parts += [f"### `{rel}`", "", f"```{lang}", text, "```", ""]

    return "\n".join(parts)
