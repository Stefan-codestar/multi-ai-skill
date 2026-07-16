from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class Draft:
    model: str
    content: str
    ok: bool
    error: str | None
    latency_s: float


def _call_one(provider, model, messages, timeout, max_tokens, temperature, extra_body=None) -> Draft:
    start = time.perf_counter()
    try:
        content = provider.complete(
            model, messages, timeout=timeout, max_tokens=max_tokens, temperature=temperature,
            extra_body=extra_body,
        )
        latency = time.perf_counter() - start
        return Draft(model=model, content=content, ok=True, error=None, latency_s=latency)
    except Exception as e:
        latency = time.perf_counter() - start
        return Draft(model=model, content="", ok=False, error=str(e), latency_s=latency)


def fan_out(provider, messages, models, *, timeout=60, max_tokens=4096, temperature=0.7, max_workers=None, extra_body=None):
    if not models:
        return []
    if max_workers is None:
        max_workers = len(models)
    drafts: list[Draft | None] = [None] * len(models)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        fut_to_idx = {
            executor.submit(
                _call_one, provider, model, messages, timeout, max_tokens, temperature,
                dict(extra_body) if extra_body else None,
            ): i
            for i, model in enumerate(models)
        }
        for future in as_completed(fut_to_idx):
            drafts[fut_to_idx[future]] = future.result()
    return drafts
