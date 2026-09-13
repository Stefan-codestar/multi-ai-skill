from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from .aggregate import concat_drafts, synthesize, synthesize_stream
from .config import DEFAULT_LOG_DIR, MultiAIConfig
from .council import EFFORT_ORDER, ROLE_EFFORT, render_brief, render_seats
from .fanout import Draft, fan_out
from .logio import log_run
from .modelresolve import load_catalog, resolve, resolve_all
from .providers import RoutingProvider

# Strategien, deren Ausgabe ein AUFTRAG an Claude Code ist und keine fertige
# Antwort an den Nutzer.
EXTERNAL_SYNTHESIS_STRATEGIES = frozenset({"brief", "seats"})

# Default-State-Pfad fuer den modelcheck.
MODELCHECK_STATE_PATH = os.path.join(DEFAULT_LOG_DIR, "modelcheck.json")


def _apply_catalog_resolution(config: MultiAIConfig) -> list[str]:
    """Biegt konfigurierte Modellnamen auf real existierende Tags um.

    Mutiert ``config`` in-place und gibt Hinweiszeilen fuer den Nutzer zurueck.
    Wird nur fuer netzgebundene Strategien aufgerufen; ``seats`` braucht keinen
    Katalog. Bei nicht erreichbarem Katalog passiert nichts.
    """
    catalog = load_catalog()
    if not catalog:
        return []

    notes: list[str] = []

    config.worker_models, changes = resolve_all(config.worker_models, catalog)
    for before, after in changes:
        notes.append(f"Sitz-Modell '{before}' nicht im Katalog — weiche auf '{after}' aus.")

    # Der Aggregator zaehlt mit: im vps-Profil ist er ein HTTP-Modell und faellt
    # sonst genauso still aus wie ein Sitz.
    resolved_aggregator = resolve(config.aggregator_model, catalog)
    if resolved_aggregator != config.aggregator_model:
        notes.append(
            f"Aggregator '{config.aggregator_model}' nicht im Katalog — "
            f"weiche auf '{resolved_aggregator}' aus."
        )
        config.aggregator_model = resolved_aggregator

    return notes


@dataclass
class Result:
    final: str
    drafts: list[Draft]
    aggregator_model: str
    strategy: str
    used_quorum: bool
    n_ok: int
    profile: str = ""
    council_size: int = 0
    modelcheck_warning: str = ""

    @property
    def needs_external_synthesis(self) -> bool:
        """True, wenn ``final`` noch von Claude Code synthetisiert werden muss."""
        return self.strategy in EXTERNAL_SYNTHESIS_STRATEGIES

    @property
    def degraded(self) -> bool:
        """True, wenn der Rat das Quorum NICHT erreicht hat.

        Sprechender Name fuer ``used_quorum``, das aus dem Vorgaenger-Skill
        stammt und genau umgekehrt klingt, als es bedeutet. ``used_quorum``
        bleibt fuer bestehende Aufrufer erhalten.
        """
        return self.used_quorum


def _build_record(question: str, drafts: list[Draft], final: str, strategy: str,
                  aggregator_model: str, n_ok: int, total_s: float,
                  profile: str = "", advocate: bool = False) -> dict:
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": question,
        "profile": profile,
        "strategy": strategy,
        "aggregator": aggregator_model,
        "total_s": total_s,
        "n_ok": n_ok,
        "advocate": advocate,
        "drafts": [
            {
                "model": d.model,
                "role": d.role,
                "seat": d.seat,
                "ok": d.ok,
                "latency_s": d.latency_s,
                "error": d.error,
                "content": d.content,
                "words": len((d.content or "").split()),
            }
            for d in drafts
        ],
        "final": final,
        "final_words": len((final or "").split()),
    }


def _log(config: MultiAIConfig, record_args: tuple) -> None:
    """Best effort — Logging darf eine fertige Antwort niemals gefaehrden."""
    if not config.enable_logging:
        return
    try:
        log_run(_build_record(*record_args), config.log_dir)
    except Exception:
        pass


def _convene(provider, question: str, config: MultiAIConfig) -> list[Draft]:
    """Ruft die sieben Sitze in Wellen auf (begrenzt durch ``max_parallel``).

    Pro Sitz wird ``config.extra_body_for(i)`` verwendet — Reasoning-Effort
    variiert nach Rolle (Vorschlag 5). Die Sitze werden nach Reasoning-Effort
    sortiert, damit schnelle Modelle in Welle 1 laufen (Vorschlag 7).

    Quorum-Early-Exit (Vorschlag 7): Nach jeder Welle wird geprueft, ob genug
    Sitze erfolgreich geantwortet haben (>= ``quorum_k``). Wenn ja, werden
    verbleibende Wellen nicht mehr gestartet — die langsamsten Sitze fallen weg.

    Mission 14 (Rat-Lauf 15, M4) — rotierender Adversarial Advocate:
    Bei ``config.advocate`` erhaelt EIN zufaelliger Sitz einen
    Gegenargument-Append auf seinen Lens-Prompt. Die anderen Sitze erfahren
    nichts davon. Auswahl deterministisch pro Lauf (Random aus time.time()-Seed
    via random.Random(ts)), damit Auswertungen reproduzierbar bleiben.
    """
    from dataclasses import replace as _dc_replace
    import random as _random
    import time as _time

    n = config.council_size
    extra_bodies = [config.extra_body_for(i) for i in range(n)]

    # Advocate-Sitz bestimmen (nur wenn Rat tagt, nicht bei leerem Rat).
    advocate_seat: int | None = None
    if config.advocate and n > 0:
        ts_seed = int(_time.time())
        advocate_seat = _random.Random(ts_seed).randrange(n)

    ADVOCATE_APPEND = (
        "\n\n---\n\n"
        "ADVOCATUS DIABOLI (nur fuer DICH, diese Sitzung):\n"
        "Nenne ZUSAETZLICH zu deinem Beitrag das staerkste Gegenargument "
        "zu deiner eigenen Position. Wenn kein Gegenargument existiert, "
        "schreibe explizit: KEIN GEGENARGUMENT.\n"
        "Markiere den Abschnitt mit 'GEGENARGUMENT:' am Anfang.\n"
    )

    # Sortiere Sitze nach Reasoning-Effort (low -> xhigh) fuer Wellen-Sortierung.
    # Behalte die Original-Indizes fuer Lenses und Roles.
    indexed = list(range(n))
    indexed.sort(
        key=lambda i: EFFORT_ORDER.get(
            extra_bodies[i].get("reasoning_effort", "xhigh"), 3
        )
    )

    sorted_models = [config.worker_models[i] for i in indexed]
    sorted_extra_bodies = [extra_bodies[i] for i in indexed]
    sorted_lenses = [config.lens_for(i) for i in indexed]
    sorted_roles = [config.role_for(i) for i in indexed]

    # Mission 14 (M4): Advocate-Append auf den Lens-Prompt des gewaehlten
    # Sitzes. Lens None (Lenses aus) -> Append wird selbst der System-Prompt.
    if advocate_seat is not None:
        for pos, orig_idx in enumerate(indexed):
            if orig_idx == advocate_seat:
                base_lens = sorted_lenses[pos]
                sorted_lenses[pos] = (
                    (base_lens + ADVOCATE_APPEND) if base_lens else ADVOCATE_APPEND.strip()
                )

    result: list[Draft | None] = [None] * n  # type: ignore
    n_ok = 0
    max_parallel = max(1, config.max_parallel)

    for wave_start in range(0, n, max_parallel):
        wave_end = min(wave_start + max_parallel, n)
        wave_models = sorted_models[wave_start:wave_end]
        wave_ebs = sorted_extra_bodies[wave_start:wave_end]
        wave_lenses = sorted_lenses[wave_start:wave_end]
        wave_roles = sorted_roles[wave_start:wave_end]
        wave_indices = indexed[wave_start:wave_end]

        wave_drafts = fan_out(
            provider,
            [{"role": "user", "content": question}],
            wave_models,
            timeout=config.timeout_s,
            max_tokens=config.worker_max_tokens,
            temperature=config.worker_temperature,
            extra_bodies=wave_ebs,
            max_workers=len(wave_models),
            lenses=wave_lenses,
            roles=wave_roles,
        )

        for draft, orig_idx in zip(wave_drafts, wave_indices):
            result[orig_idx] = _dc_replace(draft, seat=orig_idx + 1)
            if draft.ok:
                n_ok += 1

    return result  # type: ignore[return-value]


def _run_modelcheck_warning() -> str:
    """Fuehrt den modelcheck aus und liefert eine Warnung, wenn Aenderungen gefunden wurden.

    Blockiert den Lauf nicht. Wenn der Check nicht faellig ist oder keine
    Aenderungen findet, wird ein leerer String zurueckgegeben.
    """
    try:
        from . import modelcheck
        _ran, report = modelcheck.run_check(state_path=MODELCHECK_STATE_PATH)
    except Exception:
        return ""
    if not _ran:
        return ""
    # "nicht faellig" -> kein Lauf; "KEINE AENDERUNGEN" / "BASELINE ERSTELLT" -> ok
    first_line = report.splitlines()[0] if report else ""
    if "nicht faellig" in report or first_line.startswith("KEINE AENDERUNGEN") or first_line.startswith("BASELINE ERSTELLT"):
        return ""
    return report


def run_multiai(
    question: str,
    config: MultiAIConfig | None = None,
    provider: Any | None = None,
) -> Result:
    """Laesst den Rat tagen und liefert das Ergebnis der gewaehlten Strategie."""
    config = config or MultiAIConfig()
    config.validate()

    # Solo-Modus braucht weder Provider noch Netz.
    if config.strategy == "seats":
        final = render_seats(question, config)
        return Result(
            final=final, drafts=[], aggregator_model=config.aggregator_model,
            strategy="seats", used_quorum=True, n_ok=0,
            profile=config.profile, council_size=config.council_size,
        )

    if provider is None:
        provider = RoutingProvider(ollama_base_url=config.base_url)

    resolution_notes = _apply_catalog_resolution(config)

    # Vorschlag 8: modelcheck vor jedem Lauf (informell, nicht blockierend)
    modelcheck_warning = _run_modelcheck_warning()
    if resolution_notes:
        modelcheck_warning = "\n".join([*resolution_notes, modelcheck_warning or ""]).strip()

    t0 = time.time()
    drafts = _convene(provider, question, config)
    n_ok = sum(1 for d in drafts if d.ok)
    aggregator_model = config.aggregator_model
    strategy = config.strategy

    if strategy == "concat":
        final = concat_drafts(drafts)
        used_quorum = False
    elif strategy == "brief":
        # Claude Code (Opus 5) ist der Aggregator — hier entsteht nur sein Auftrag.
        final = render_brief(question, drafts, config)
        used_quorum = n_ok < config.quorum_k
    elif strategy == "moa":
        if n_ok >= 1:
            try:
                final = synthesize(
                    provider, question, drafts,
                    aggregator_model=aggregator_model,
                    max_tokens=config.aggregator_max_tokens,
                    temperature=config.aggregator_temperature,
                    extra_body=config.aggregator_extra_body,
                )
            except Exception as agg_err:
                # Aggregator-Crash (HTTP-Fehler, Timeout, 429).
                # Vorschlag 1: Bei HTTP-Profil (vps/strategy=moa) wird der
                # Aggregator mit der Frage allein gerufen — auf dem VPS gibt
                # es kein Claude Code als Fallback. Bei strategy=brief (claude)
                # bleibt der Brief als Fallback erhalten.
                final = provider.complete(
                    aggregator_model,
                    [{"role": "user", "content": (
                        f"Antworte direkt auf diese Frage ohne Rat-Beitraege: {question}"
                    )}],
                    temperature=config.aggregator_temperature,
                    max_tokens=config.aggregator_max_tokens,
                    extra_body=config.aggregator_extra_body,
                )
                final = (
                    f"[Aggregator-Fallback: {agg_err} — "
                    f"Aggregator antwortet allein ohne Rat-Beitraege]\n\n{final}"
                )
            used_quorum = n_ok < config.quorum_k
        else:
            # Kein Sitz erreichbar -> der Aggregator antwortet allein.
            final = provider.complete(
                aggregator_model,
                [{"role": "user", "content": question}],
                temperature=config.aggregator_temperature,
                max_tokens=config.aggregator_max_tokens,
                extra_body=config.aggregator_extra_body,
            )
            used_quorum = True
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")

    total_s = time.time() - t0
    _log(config, (question, drafts, final, strategy, aggregator_model, n_ok,
                  total_s, config.profile, bool(config.advocate)))

    return Result(
        final=final,
        drafts=drafts,
        aggregator_model=aggregator_model,
        strategy=strategy,
        used_quorum=used_quorum,
        n_ok=n_ok,
        profile=config.profile,
        council_size=config.council_size,
        modelcheck_warning=modelcheck_warning,
    )


def run_multiai_stream(
    question: str,
    config: MultiAIConfig | None = None,
    provider: Any | None = None,
):
    """Wie :func:`run_multiai`, streamt aber die Synthese chunkweise.

    Nur fuer Profile mit HTTP-Aggregator sinnvoll. Bei ``brief``/``seats`` gibt es
    nichts zu streamen — die Ausgabe wird am Stueck geliefert.
    """
    config = config or MultiAIConfig()
    config.validate()

    if config.strategy == "seats":
        yield render_seats(question, config)
        return

    if provider is None:
        provider = RoutingProvider(ollama_base_url=config.base_url)

    _apply_catalog_resolution(config)

    t0 = time.time()
    drafts = _convene(provider, question, config)
    n_ok = sum(1 for d in drafts if d.ok)
    aggregator_model = config.aggregator_model
    strategy = config.strategy

    if strategy == "concat":
        final = concat_drafts(drafts)
        yield final
    elif strategy == "brief":
        final = render_brief(question, drafts, config)
        yield final
    elif strategy == "moa":
        if n_ok >= 1:
            try:
                parts: list[str] = []
                for chunk in synthesize_stream(
                    provider, question, drafts,
                    aggregator_model=aggregator_model,
                    max_tokens=config.aggregator_max_tokens,
                    temperature=config.aggregator_temperature,
                    extra_body=config.aggregator_extra_body,
                ):
                    parts.append(chunk)
                    yield chunk
                final = "".join(parts)
            except Exception as agg_err:
                # Aggregator-Crash -> Fallback: Aggregator antwortet allein (Vorschlag 1)
                final = provider.complete(
                    aggregator_model,
                    [{"role": "user", "content": (
                        f"Antworte direkt auf diese Frage ohne Rat-Beitraege: {question}"
                    )}],
                    temperature=config.aggregator_temperature,
                    max_tokens=config.aggregator_max_tokens,
                    extra_body=config.aggregator_extra_body,
                )
                final = (
                    f"[Aggregator-Fallback: {agg_err} — "
                    f"Aggregator antwortet allein ohne Rat-Beitraege]\n\n{final}"
                )
                yield final
        else:
            final = provider.complete(
                aggregator_model,
                [{"role": "user", "content": question}],
                temperature=config.aggregator_temperature,
                max_tokens=config.aggregator_max_tokens,
                extra_body=config.aggregator_extra_body,
            )
            yield final
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")

    total_s = time.time() - t0
    _log(config, (question, drafts, final, strategy, aggregator_model, n_ok,
                  total_s, config.profile, bool(config.advocate)))
