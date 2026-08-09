"""Rat der Sieben — Sitz-Definitionen und Umgebungsprofile.

Der Rat besteht aus sieben *Sitzen*. Jeder Sitz hat

1. ein eigenes **Modell** (anderes Lab, anderes Land, andere Architektur) und
2. eine eigene **Rolle** (Lens) — ein System-Prompt, der die Perspektive vorgibt.

Diese zwei Achsen zusammen erzeugen die Diversitaet: selbst wenn zwei Modelle
aehnlich trainiert wurden, argumentieren sie aus unterschiedlichen Blickwinkeln.

Zwei Profile:

- ``vps``    — Hermes VPS. Alles laeuft ueber Ollama Cloud. Aggregator ``glm-5.2``.
- ``claude`` — Claude Code. Die sieben Sitze laufen ueber Ollama Cloud, der
  Aggregator ist Opus 5 **in-process**: Claude Code selbst synthetisiert und
  braucht dafuer keinen zusaetzlichen API-Call.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


# ── Sitz-Rollen (Lenses) ───────────────────────────────────────────────────
#
# Sieben klar getrennte Blickwinkel. Bewusst so formuliert, dass sich die
# Antworten NICHT ueberlappen — ein Rat, in dem alle dasselbe sagen, ist
# wertlos. Jede Lens endet mit einer Laengen-/Fokusvorgabe, damit die
# Entwuerfe fuer die Synthese handhabbar bleiben.

LENS_ANALYST = (
    "Du bist DER ANALYTIKER im Rat der Sieben. Zerlege die Frage in ihre Bestandteile, "
    "mache implizite Annahmen explizit und pruefe die Logik Schritt fuer Schritt. "
    "Wo Zahlen, Definitionen oder Kausalketten im Spiel sind, arbeite sie sauber heraus. "
    "Priorisiere Korrektheit vor Vollstaendigkeit. Antworte strukturiert und praezise."
)

LENS_ENGINEER = (
    "Du bist DER INGENIEUR im Rat der Sieben. Beantworte die Frage aus Sicht der "
    "konkreten Umsetzung: Was muss gebaut, geaendert oder konfiguriert werden? "
    "Nenne konkrete Schritte, Werkzeuge, Schnittstellen und Stolperfallen bei der "
    "Implementierung. Vermeide Abstraktionen ohne praktischen Bezug."
)

LENS_SKEPTIC = (
    "Du bist DER SKEPTIKER im Rat der Sieben. Deine Aufgabe ist Red-Teaming: suche "
    "Fehler, Gegenbeispiele, Fehlannahmen und Risiken — auch in der Frage selbst. "
    "Was koennte schiefgehen? Was wird uebersehen? Wo ist die naheliegende Antwort "
    "falsch? Sei konkret statt allgemein warnend. Wenn die naheliegende Antwort "
    "tatsaechlich richtig ist, sage das ebenfalls klar."
)

LENS_STRATEGIST = (
    "Du bist DER STRATEGE im Rat der Sieben. Betrachte die langfristigen Folgen: "
    "Welche Option altert am besten? Welche Trade-offs entstehen, welche Tueren "
    "werden zugemacht? Vergleiche echte Alternativen gegeneinander statt nur eine "
    "zu beschreiben. Denke in Konsequenzen, nicht in Features."
)

LENS_PRAGMATIST = (
    "Du bist DER PRAGMATIKER im Rat der Sieben. Suche die einfachste Loesung, die "
    "das Problem wirklich loest. Bewerte Aufwand gegen Nutzen, benenne, was man "
    "weglassen kann (YAGNI), und was 80 Prozent des Werts mit 20 Prozent des "
    "Aufwands bringt. Misstraue Ueberkonstruktion."
)

LENS_EXPLAINER = (
    "Du bist DER ERKLAERER im Rat der Sieben. Sorge fuer Klarheit: bringe die Sache "
    "auf den Punkt, benutze ein treffendes Beispiel oder eine Analogie und mache "
    "die Antwort fuer jemanden verstaendlich, der nicht taeglich damit arbeitet. "
    "Klarheit ist wichtiger als Vollstaendigkeit."
)

LENS_MAVERICK = (
    "Du bist DER QUERDENKER im Rat der Sieben. Stelle die Rahmung der Frage in "
    "Frage und schlage einen Ansatz vor, auf den die anderen nicht kommen wuerden. "
    "Gibt es eine ganz andere Problemsicht? Eine unkonventionelle, aber tragfaehige "
    "Loesung? Bleibe dabei ernsthaft und begruendet — kein Selbstzweck-Kontrarismus."
)


@dataclass(frozen=True)
class Seat:
    """Ein Sitz im Rat: Rolle + Modell + Herkunft."""

    role: str          # "Analytiker"
    lens: str          # System-Prompt der Rolle
    model: str         # "deepseek-v4-pro"
    lab: str           # "DeepSeek"
    country: str       # "CN"
    strength: str      # kurze Begruendung fuer die Zuordnung


# ── Modell-Stammdaten ──────────────────────────────────────────────────────
# Herkunft der Modelle im Ollama-Cloud-Katalog. Wird fuer den
# Diversitaets-Report und die Doku genutzt.

MODEL_ORIGINS: dict[str, tuple[str, str]] = {
    "deepseek-v4-pro":       ("DeepSeek", "CN"),
    "qwen3.5:397b":          ("Alibaba", "CN"),
    "nemotron-3-ultra":      ("NVIDIA", "US"),
    "minimax-m3":            ("MiniMax", "CN"),
    "gpt-oss:120b":          ("OpenAI", "US"),
    "mistral-large-3:675b":  ("Mistral", "FR"),
    "kimi-k2.6":             ("Moonshot", "CN"),
    "glm-5.2":               ("Z.ai", "CN"),
    "claude-opus-5":         ("Anthropic", "US"),
}


def _origin(model: str) -> tuple[str, str]:
    return MODEL_ORIGINS.get(model, ("unbekannt", "??"))


def _seat(role: str, lens: str, model: str, strength: str) -> Seat:
    lab, country = _origin(model)
    return Seat(role=role, lens=lens, model=model, lab=lab, country=country, strength=strength)


# ── Die sieben Sitze ───────────────────────────────────────────────────────
# Reihenfolge ist stabil und wird in Ausgaben so beibehalten.

def _base_seats(strategist_model: str) -> list[Seat]:
    """Die sieben Sitze; nur der Sitz des Strategen unterscheidet sich je Profil.

    Im VPS-Profil ist ``glm-5.2`` der Aggregator und darf deshalb nicht auf einem
    Sitz sitzen (Self-Bias). Im Claude-Profil aggregiert Opus 5, wodurch
    ``glm-5.2`` als Sitz frei wird.
    """
    return [
        _seat("Analytiker",  LENS_ANALYST,     "deepseek-v4-pro",
              "Deep Reasoning, starke Ketten-Logik"),
        _seat("Ingenieur",   LENS_ENGINEER,    "qwen3.5:397b",
              "Code, Mathe, praezise Instruktionsbefolgung"),
        _seat("Skeptiker",   LENS_SKEPTIC,     "nemotron-3-ultra",
              "US-Perspektive, breites Faktenwissen fuer Gegenbeispiele"),
        _seat("Stratege",    LENS_STRATEGIST,  strategist_model,
              "Langer Kontext, Abwaegung ueber viele Optionen"),
        _seat("Pragmatiker", LENS_PRAGMATIST,  "gpt-oss:120b",
              "Kompakt und direkt, neigt zu einfachen Loesungen"),
        _seat("Erklaerer",   LENS_EXPLAINER,   "mistral-large-3:675b",
              "Fluessige Sprache, europaeische Perspektive"),
        _seat("Querdenker",  LENS_MAVERICK,    "kimi-k2.6",
              "Unkonventionelle Ansaetze, ungewoehnliche Rahmungen"),
    ]


COUNCIL_SIZE = 7


@dataclass(frozen=True)
class Profile:
    """Eine Umgebung, in der der Rat tagt."""

    name: str
    seats: list[Seat]
    aggregator_model: str
    aggregator_kind: str        # "http" | "inprocess"
    aggregator_lab: str
    aggregator_country: str
    default_strategy: str
    base_url: str
    max_parallel: int
    description: str
    supports_stream: bool = True

    @property
    def worker_models(self) -> list[str]:
        return [s.model for s in self.seats]

    @property
    def lenses(self) -> list[str]:
        return [s.lens for s in self.seats]

    def seat_by_role(self, role: str) -> Seat | None:
        low = role.strip().lower()
        for s in self.seats:
            if s.role.lower() == low:
                return s
        return None


OLLAMA_BASE_URL = "https://ollama.com/v1"


PROFILE_VPS = Profile(
    name="vps",
    seats=_base_seats(strategist_model="minimax-m3"),
    aggregator_model="glm-5.2",
    aggregator_kind="http",
    aggregator_lab="Z.ai",
    aggregator_country="CN",
    default_strategy="moa",
    base_url=OLLAMA_BASE_URL,
    max_parallel=3,          # Ollama Cloud Pro: 3 gleichzeitige Modelle
    description=(
        "Hermes VPS — alle sieben Sitze und der Aggregator laufen ueber Ollama Cloud. "
        "Aggregator: glm-5.2."
    ),
    supports_stream=True,
)


PROFILE_CLAUDE = Profile(
    name="claude",
    # glm-5.2 ist hier NICHT Aggregator und darf deshalb einen Sitz einnehmen.
    seats=_base_seats(strategist_model="glm-5.2"),
    aggregator_model="claude-opus-5",
    aggregator_kind="inprocess",
    aggregator_lab="Anthropic",
    aggregator_country="US",
    default_strategy="brief",
    base_url=OLLAMA_BASE_URL,
    max_parallel=3,
    description=(
        "Claude Code — die sieben Sitze laufen ueber Ollama Cloud, aggregiert wird "
        "in-process von Opus 5 (kein zusaetzlicher API-Call, kein zweiter Key)."
    ),
    supports_stream=False,   # der Aggregator ist Claude Code selbst
)


PROFILES: dict[str, Profile] = {
    "vps": PROFILE_VPS,
    "claude": PROFILE_CLAUDE,
}

DEFAULT_PROFILE_NAME = "claude"


def get_profile(name: str | None) -> Profile:
    """Liefert ein Profil per Name. Unbekannter Name -> ValueError mit Auswahl."""
    key = (name or DEFAULT_PROFILE_NAME).strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unbekanntes Profil: {name!r}. Verfuegbar: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[key]


def with_models(profile: Profile, models: list[str]) -> Profile:
    """Setzt die Modelle der Sitze neu (CLI ``--models``), Rollen bleiben erhalten.

    Sind weniger Modelle als Sitze angegeben, schrumpft der Rat entsprechend;
    sind es mehr, werden die ueberzaehligen Modelle auf zusaetzliche Sitze mit
    rotierenden Rollen verteilt.
    """
    if not models:
        return profile
    base = profile.seats
    new_seats: list[Seat] = []
    for i, model in enumerate(models):
        template = base[i % len(base)]
        lab, country = _origin(model)
        new_seats.append(replace(template, model=model, lab=lab, country=country))
    return replace(profile, seats=new_seats)


def diversity_report(profile: Profile) -> str:
    """Kurzer Text: welche Labs/Laender im Rat vertreten sind."""
    labs = {s.lab for s in profile.seats}
    countries: dict[str, int] = {}
    for s in profile.seats:
        countries[s.country] = countries.get(s.country, 0) + 1
    spread = ", ".join(f"{c}:{n}" for c, n in sorted(countries.items()))
    return (
        f"{len(profile.seats)} Sitze | {len(labs)} Labs | Laender {spread} "
        f"| Aggregator {profile.aggregator_model} ({profile.aggregator_lab}, "
        f"{profile.aggregator_country})"
    )


def all_worker_models() -> list[str]:
    """Alle Sitz-Modelle beider Profile, dedupliziert und sortiert.

    Grundlage fuer den Verfuegbarkeits-Check: beide Profile sollen ueberwacht
    werden, egal auf welcher Maschine der Check laeuft.
    """
    seen: set[str] = set()
    for profile in PROFILES.values():
        seen.update(profile.worker_models)
    return sorted(seen)


def all_http_models() -> list[str]:
    """Alle Modelle, die tatsaechlich per HTTP beim Provider angefragt werden.

    Enthaelt zusaetzlich die HTTP-Aggregatoren, aber nicht den in-process
    Aggregator (Opus 5 laeuft nicht ueber den Provider).
    """
    models = set(all_worker_models())
    for profile in PROFILES.values():
        if profile.aggregator_kind == "http":
            models.add(profile.aggregator_model)
    return sorted(models)
