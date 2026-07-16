from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .aggregate import concat_drafts, synthesize, synthesize_stream
from .config import MultiAIConfig
from .fanout import Draft, fan_out
from .logio import log_run
from .providers import OllamaCloudProvider, RoutingProvider


@dataclass
class Result:
    final: str
    drafts: list[Draft]
    aggregator_model: str
    strategy: str
    used_quorum: bool
    n_ok: int


def _build_record(question: str, drafts: list[Draft], final: str, strategy: str,
                  aggregator_model: str, n_ok: int, total_s: float) -> dict:
    return {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": question,
        "strategy": strategy,
        "aggregator": aggregator_model,
        "total_s": total_s,
        "n_ok": n_ok,
        "drafts": [
            {
                "model": d.model,
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


def run_multiai(
    question: str,
    config: MultiAIConfig | None = None,
    provider: Any | None = None,
) -> Result:
    """Fuehrt die MultiAI-Pipeline aus: paralleler Fanout, MoA-Synthese, optionales Logging."""
    config = config or MultiAIConfig()
    if provider is None:
        provider = RoutingProvider(ollama_base_url=config.base_url)  # Ollama + OpenRouter (google/*)

    t0 = time.time()
    messages = [{"role": "user", "content": question}]
    # Worker laufen PARALLEL (fan_out) — inkl. glm-5.2, das auch als Proposer mitwirkt.
    drafts = fan_out(
        provider,
        messages,
        config.worker_models,
        timeout=config.timeout_s,
        max_tokens=config.worker_max_tokens,
        temperature=config.worker_temperature,
        extra_body=config.worker_extra_body,
    )
    n_ok = sum(1 for d in drafts if d.ok)
    aggregator_model = config.aggregator_model
    strategy = config.strategy

    if strategy == "concat":
        final = concat_drafts(drafts)
        used_quorum = False
    elif strategy == "moa":
        if n_ok >= config.quorum_k:
            final = synthesize(
                provider, question, drafts,
                aggregator_model=aggregator_model,
                max_tokens=config.aggregator_max_tokens,
                temperature=config.aggregator_temperature,
                extra_body=config.aggregator_extra_body,
            )
            used_quorum = False
        elif n_ok >= 1:
            # Degradation: weniger als quorum_k, aber synthetisieren mit dem Vorhandenen.
            final = synthesize(
                provider, question, drafts,
                aggregator_model=aggregator_model,
                max_tokens=config.aggregator_max_tokens,
                temperature=config.aggregator_temperature,
                extra_body=config.aggregator_extra_body,
            )
            used_quorum = True
        else:
            # Kein Worker erfolgreich -> Lead (glm-5.2) antwortet allein.
            final = provider.complete(
                aggregator_model,
                messages,
                temperature=config.aggregator_temperature,
                max_tokens=config.aggregator_max_tokens,
                extra_body=config.aggregator_extra_body,
            )
            used_quorum = True
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")

    total_s = time.time() - t0

    if config.enable_logging:
        # Logging ist best-effort und darf die Antwort NIE gefaehrden (inkl. _build_record).
        try:
            log_run(
                _build_record(question, drafts, final, strategy, aggregator_model, n_ok, total_s),
                config.log_dir,
            )
        except Exception:
            pass

    return Result(
        final=final,
        drafts=drafts,
        aggregator_model=aggregator_model,
        strategy=strategy,
        used_quorum=used_quorum,
        n_ok=n_ok,
    )


def run_multiai_stream(
    question: str,
    config: MultiAIConfig | None = None,
    provider: Any | None = None,
):
    """Wie run_multiai, aber streamt die Synthesizer-Antwort chunkweise.

    Yieldt str-Chunks mit Content-Deltas vom Synthesizer.
    Die Worker-Phase bleibt parallel (unchanged) — nur die Synthese wird gestreamt.

    Am Ende wird ein Run-Log geschrieben (best-effort).
    """
    import sys

    config = config or MultiAIConfig()
    if provider is None:
        provider = RoutingProvider(ollama_base_url=config.base_url)

    t0 = time.time()
    messages = [{"role": "user", "content": question}]

    # Worker parallel (wie gehabt)
    drafts = fan_out(
        provider,
        messages,
        config.worker_models,
        timeout=config.timeout_s,
        max_tokens=config.worker_max_tokens,
        temperature=config.worker_temperature,
        extra_body=config.worker_extra_body,
    )
    n_ok = sum(1 for d in drafts if d.ok)
    aggregator_model = config.aggregator_model
    strategy = config.strategy

    if strategy == "concat":
        final = concat_drafts(drafts)
        yield final
        used_quorum = False
    elif strategy == "moa":
        if n_ok >= 1:
            final_parts: list[str] = []
            for chunk in synthesize_stream(
                provider, question, drafts,
                aggregator_model=aggregator_model,
                max_tokens=config.aggregator_max_tokens,
                temperature=config.aggregator_temperature,
                extra_body=config.aggregator_extra_body,
            ):
                final_parts.append(chunk)
                yield chunk
            final = "".join(final_parts)
            used_quorum = n_ok < config.quorum_k
        else:
            final = provider.complete(
                aggregator_model,
                messages,
                temperature=config.aggregator_temperature,
                max_tokens=config.aggregator_max_tokens,
                extra_body=config.aggregator_extra_body,
            )
            yield final
            used_quorum = True
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")

    total_s = time.time() - t0

    if config.enable_logging:
        try:
            log_run(
                _build_record(question, drafts, final, strategy, aggregator_model, n_ok, total_s),
                config.log_dir,
            )
        except Exception:
            pass
