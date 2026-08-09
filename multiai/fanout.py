from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class Draft:
    """Der Beitrag eines Sitzes zum Rat."""

    model: str
    content: str
    ok: bool
    error: str | None
    latency_s: float
    role: str = ""       # "Skeptiker" — leer, wenn ohne Rollen gefahren wird
    seat: int = 0        # Position im Rat, 1-basiert

    @property
    def label(self) -> str:
        """Anzeigename: 'Skeptiker (nemotron-3-ultra)' bzw. nur das Modell."""
        return f"{self.role} ({self.model})" if self.role else self.model


def _with_lens(messages: list[dict[str, str]], lens: str | None) -> list[dict[str, str]]:
    """Stellt der Nachrichtenliste den Lens-System-Prompt des Sitzes voran.

    Ein bereits vorhandener System-Prompt bleibt erhalten und wird an die Lens
    angehaengt, damit Aufrufer eigene Instruktionen mitgeben koennen.
    """
    if not lens:
        return messages
    head = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if head:
        merged = lens + "\n\n" + "\n\n".join(m.get("content", "") for m in head)
    else:
        merged = lens
    return [{"role": "system", "content": merged}, *rest]


def _call_one(
    provider,
    model,
    messages,
    timeout,
    max_tokens,
    temperature,
    extra_body=None,
    lens=None,
    role="",
    seat=0,
) -> Draft:
    start = time.perf_counter()
    try:
        content = provider.complete(
            model,
            _with_lens(messages, lens),
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        )
        latency = time.perf_counter() - start
        return Draft(
            model=model, content=content, ok=True, error=None,
            latency_s=latency, role=role, seat=seat,
        )
    except Exception as e:
        latency = time.perf_counter() - start
        return Draft(
            model=model, content="", ok=False, error=str(e),
            latency_s=latency, role=role, seat=seat,
        )


def fan_out(
    provider,
    messages,
    models,
    *,
    timeout=60,
    max_tokens=4096,
    temperature=0.7,
    max_workers=None,
    extra_body=None,
    extra_bodies=None,
    lenses=None,
    roles=None,
):
    """Ruft alle Sitze parallel auf und liefert die Entwuerfe in Sitz-Reihenfolge.

    ``lenses`` und ``roles`` sind optionale Parallel-Listen zu ``models``.
    ``extra_bodies`` ist eine optionale Parallel-Liste zu ``models`` mit
    pro-Sitz ``extra_body``-Dicts; es hat Vorrang vor dem skalaren ``extra_body``.
    ``max_workers`` begrenzt die Gleichzeitigkeit — auf Ollama Cloud Pro sind
    nur drei Modelle gleichzeitig aktiv, mehr Threads bringen dort nichts und
    lassen die ueberzaehligen Anfragen in den Timeout laufen.
    """
    if not models:
        return []
    if max_workers is None:
        max_workers = len(models)
    max_workers = max(1, min(max_workers, len(models)))

    drafts: list[Draft | None] = [None] * len(models)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        fut_to_idx = {
            executor.submit(
                _call_one,
                provider,
                model,
                messages,
                timeout,
                max_tokens,
                temperature,
                (dict(extra_bodies[i]) if extra_bodies and i < len(extra_bodies)
                 else dict(extra_body) if extra_body else None),
                lenses[i] if lenses and i < len(lenses) else None,
                roles[i] if roles and i < len(roles) else "",
                i + 1,
            ): i
            for i, model in enumerate(models)
        }
        for future in as_completed(fut_to_idx):
            drafts[fut_to_idx[future]] = future.result()
    return drafts
