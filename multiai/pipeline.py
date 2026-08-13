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
from .providers import RoutingProvider

# Strategien, deren Ausgabe ein AUFTRAG an Claude Code ist und keine fertige
# Antwort an den Nutzer.
EXTERNAL_SYNTHESIS_STRATEGIES = frozenset({"brief", "seats"})

# Default-State-Pfad fuer den modelcheck.
MODELCHECK_STATE_PATH = os.path.join(DEFAULT_LOG_DIR, "modelcheck.json")


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
                  profile: str = "") -> dict:
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": question,
        "profile": profile,
        "strategy": strategy,
        "aggregator": aggregator_model,
        "total_s": total_s,
        "n_ok": n_ok,
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
    """
    from dataclasses import replace as _dc_replace

    n = config.council_size
    extra_bodies = [config.extra_body_for(i) for i in range(n)]

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

    # Vorschlag 8: modelcheck vor jedem Lauf (informell, nicht blockierend)
    modelcheck_warning = _run_modelcheck_warning()

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
                  total_s, config.profile))

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
                  total_s, config.profile))
