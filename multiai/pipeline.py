from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .aggregate import concat_drafts, synthesize, synthesize_stream
from .config import MultiAIConfig
from .council import render_brief, render_seats
from .fanout import Draft, fan_out
from .logio import log_run
from .providers import RoutingProvider

# Strategien, deren Ausgabe ein AUFTRAG an Claude Code ist und keine fertige
# Antwort an den Nutzer.
EXTERNAL_SYNTHESIS_STRATEGIES = frozenset({"brief", "seats"})


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

    @property
    def needs_external_synthesis(self) -> bool:
        """True, wenn ``final`` noch von Claude Code synthetisiert werden muss."""
        return self.strategy in EXTERNAL_SYNTHESIS_STRATEGIES


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
    """Ruft die sieben Sitze parallel auf (begrenzt durch ``max_parallel``)."""
    return fan_out(
        provider,
        [{"role": "user", "content": question}],
        config.worker_models,
        timeout=config.timeout_s,
        max_tokens=config.worker_max_tokens,
        temperature=config.worker_temperature,
        extra_body=config.worker_extra_body,
        max_workers=config.max_parallel,
        lenses=[config.lens_for(i) for i in range(config.council_size)],
        roles=[config.role_for(i) for i in range(config.council_size)],
    )


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
            final = synthesize(
                provider, question, drafts,
                aggregator_model=aggregator_model,
                max_tokens=config.aggregator_max_tokens,
                temperature=config.aggregator_temperature,
                extra_body=config.aggregator_extra_body,
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
