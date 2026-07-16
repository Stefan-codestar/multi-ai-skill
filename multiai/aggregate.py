from __future__ import annotations

from typing import Any

from .fanout import Draft


AGGREGATOR_SYSTEM_PROMPT = (
    "You have been provided with a set of responses from various open-source models "
    "to the latest user query. Your task is to synthesize these responses into a single, "
    "high-quality response. It is crucial to critically evaluate the information provided "
    "in these responses, recognizing that some of it may be biased or incorrect. Your "
    "response should not simply replicate the given answers but should offer a refined, "
    "accurate, and comprehensive reply to the instruction. Ensure your response is "
    "well-structured, coherent, and adheres to the highest standards of accuracy and "
    "reliability.\n\nResponses from models:"
)


def concat_drafts(drafts: list) -> str:
    blocks = []
    for d in drafts:
        if not d.ok:
            continue
        blocks.append(f"## {d.model}\n\n{d.content}")
    return "\n\n---\n\n".join(blocks)


def synthesize(
    provider,
    question: str,
    drafts: list,
    *,
    aggregator_model: str = "glm-5.2",
    max_tokens: int = 8192,
    temperature: float = 0.3,
    extra_body: dict[str, Any] | None = None,
) -> str:
    ok_drafts = [d for d in drafts if d.ok]
    numbered_responses = "\n".join(f"{i + 1}. {d.content}" for i, d in enumerate(ok_drafts))
    system_content = AGGREGATOR_SYSTEM_PROMPT + "\n\n" + numbered_responses
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]
    return provider.complete(
        aggregator_model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )


def synthesize_stream(
    provider,
    question: str,
    drafts: list,
    *,
    aggregator_model: str = "glm-5.2",
    max_tokens: int = 8192,
    temperature: float = 0.3,
    extra_body: dict[str, Any] | None = None,
):
    """Wie synthesize(), aber streamt die Synthesizer-Antwort chunkweise.

    Yieldt str-Chunks mit Content-Deltas. Der Caller ist fuer die Ausgabe
    verantwortlich (z.B. print(chunk, end='', flush=True)).
    """
    ok_drafts = [d for d in drafts if d.ok]
    numbered_responses = "\n".join(f"{i + 1}. {d.content}" for i, d in enumerate(ok_drafts))
    system_content = AGGREGATOR_SYSTEM_PROMPT + "\n\n" + numbered_responses
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]
    yield from provider.stream_complete(
        aggregator_model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
