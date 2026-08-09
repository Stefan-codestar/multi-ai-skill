"""Vorlage: ein eigenes Profil zum Rat der Sieben hinzufuegen.

Anwendungsfaelle: eine dritte Maschine mit anderem Modellkatalog, ein
Sparprofil mit kleineren Modellen, ein Testprofil mit Attrappen.

Inhalt nach ``multiai/profiles.py`` uebernehmen (unterhalb von
``PROFILE_CLAUDE``) und in ``PROFILES`` eintragen. Danach steht das Profil
ueberall zur Verfuegung: ``--profile mein_profil``.

Pruefen nicht vergessen:

    python3 -m multiai --roster
    python3 -m pytest tests/ -q

``tests/test_profiles.py`` prueft JEDES eingetragene Profil auf sieben Sitze,
sieben verschiedene Labs und darauf, dass der Aggregator nicht im Rat sitzt.
Ein Profil, das diese Regeln bewusst bricht, muss dort ausgenommen werden.
"""

from __future__ import annotations

from dataclasses import replace

from multiai.profiles import (
    LENS_ANALYST,
    LENS_ENGINEER,
    LENS_EXPLAINER,
    LENS_MAVERICK,
    LENS_PRAGMATIST,
    LENS_SKEPTIC,
    LENS_STRATEGIST,
    PROFILES,
    Profile,
    Seat,
)

# ── Variante A: bestehendes Profil abwandeln ───────────────────────────────
# Am kuerzesten, wenn nur einzelne Modelle getauscht werden.

PROFILE_SPARSAM = replace(
    PROFILES["vps"],
    name="sparsam",
    description="Kleinere Modelle, deutlich schneller, spuerbar flacher.",
    max_parallel=3,
    seats=[
        replace(seat, model=model, lab=lab, country=country)
        for seat, (model, lab, country) in zip(
            PROFILES["vps"].seats,
            [
                ("deepseek-v4-flash", "DeepSeek", "CN"),
                ("nemotron-3-super", "NVIDIA", "US"),
                ("gpt-oss:20b", "OpenAI", "US"),
                ("minimax-m2.5", "MiniMax", "CN"),
                ("kimi-k2.5", "Moonshot", "CN"),
                ("gemma4:31b", "Google", "US"),
                ("glm-5.1", "Z.ai", "CN"),
            ],
        )
    ],
)


# ── Variante B: Profil von Grund auf ───────────────────────────────────────
# Noetig, sobald Rollen anders zugeordnet oder eigene Lenses genutzt werden.

def _seat(role: str, lens: str, model: str, lab: str, country: str, strength: str) -> Seat:
    return Seat(role=role, lens=lens, model=model, lab=lab, country=country,
                strength=strength)


PROFILE_EIGEN = Profile(
    name="eigen",
    seats=[
        _seat("Analytiker",  LENS_ANALYST,    "modell-1", "Lab A", "DE", "Reasoning"),
        _seat("Ingenieur",   LENS_ENGINEER,   "modell-2", "Lab B", "US", "Code"),
        _seat("Skeptiker",   LENS_SKEPTIC,    "modell-3", "Lab C", "FR", "Faktenwissen"),
        _seat("Stratege",    LENS_STRATEGIST, "modell-4", "Lab D", "CN", "langer Kontext"),
        _seat("Pragmatiker", LENS_PRAGMATIST, "modell-5", "Lab E", "US", "kompakt"),
        _seat("Erklaerer",   LENS_EXPLAINER,  "modell-6", "Lab F", "JP", "Sprache"),
        _seat("Querdenker",  LENS_MAVERICK,   "modell-7", "Lab G", "IL", "unkonventionell"),
    ],
    # "http": ein Modell synthetisiert per API-Call.
    # "inprocess": das lesende Modell (z.B. Claude Code) synthetisiert selbst;
    #              dann muss default_strategy "brief" sein.
    aggregator_model="modell-8",
    aggregator_kind="http",
    aggregator_lab="Lab H",
    aggregator_country="UK",
    default_strategy="moa",
    base_url="https://beispiel.invalid/v1",
    max_parallel=3,          # gleichzeitige Modelle des Plans
    description="Beispielprofil — Platzhalter durch echte Modelle ersetzen.",
    supports_stream=True,
)


# ── Registrieren ───────────────────────────────────────────────────────────
# In profiles.py direkt in das PROFILES-Dict eintragen:
#
#     PROFILES = {
#         "vps": PROFILE_VPS,
#         "claude": PROFILE_CLAUDE,
#         "sparsam": PROFILE_SPARSAM,
#     }
#
# Modelle, die noch nicht in MODEL_ORIGINS stehen, dort ergaenzen — sonst
# meldet der Diversitaets-Report "unbekannt" und test_all_models_have_known_
# origin schlaegt fehl.
