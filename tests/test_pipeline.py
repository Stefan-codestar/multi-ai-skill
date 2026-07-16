from __future__ import annotations

import pytest

from multiai.config import MultiAIConfig
from multiai.pipeline import run_multiai


class FakeProvider:
    """Unterscheidet Synthese-Calls (system-Message enthaelt 'Responses from models')
    von direkten Worker-/Lead-Calls.
    """

    def __init__(self, responses=None, synth="SYNTH", fail=None):
        self.responses = dict(responses or {})
        self.synth = synth
        self.fail = set(fail or [])
        self.calls = []

    def complete(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        if any(
            m.get("role") == "system" and "Responses from models" in m.get("content", "")
            for m in messages
        ):
            return self.synth
        if model in self.fail:
            raise RuntimeError(f"{model} down")
        if model in self.responses:
            return self.responses[model]
        raise RuntimeError(f"{model} unknown")


def _cfg(**kw):
    kw.setdefault("enable_logging", False)
    return MultiAIConfig.from_dict(kw)


def test_pipeline_all_ok_moa():
    provider = FakeProvider(
        responses={
            "glm-5.2": "G",
            "kimi-k2.7-code": "K",
            "deepseek-v4-pro": "D",
            "minimax-m3": "M",
            "nemotron-3-ultra": "N",
            "qwen3.5:397b": "Q",
            "mistral-large-3:675b": "ML",
            "gemini-3-flash-preview": "GF",
        },
        synth="SYNTH",
    )
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 8
    assert result.strategy == "moa"
    assert result.used_quorum is False
    assert result.final == "SYNTH"
    # glm-5.2 als Aggregator
    glm_calls = [c for c in provider.calls if c[0] == "glm-5.2"]
    # 1x Aggregator + 1x Worker = 2
    assert len(glm_calls) == 2


def test_pipeline_degradation_one_ok():
    provider = FakeProvider(
        responses={"glm-5.2": "G"},
        fail={"kimi-k2.7-code", "deepseek-v4-pro", "minimax-m3",
              "nemotron-3-ultra", "qwen3.5:397b", "mistral-large-3:675b",
              "gemini-3-flash-preview"},
        synth="SYNTH",
    )
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 1
    assert result.used_quorum is True
    assert result.final == "SYNTH"


def test_pipeline_lead_fallback_zero_ok():
    # glm-5.2 hier NICHT als Worker -> nur Lead-Fallback antwortet
    provider = FakeProvider(
        responses={"glm-5.2": "Lead-Allein"},
        fail={"kimi-k2.7-code", "minimax-m3"},
    )
    cfg = _cfg(worker_models=["kimi-k2.7-code", "minimax-m3"])
    result = run_multiai("Frage?", config=cfg, provider=provider)
    assert result.n_ok == 0
    assert result.used_quorum is True
    assert result.final == "Lead-Allein"


def test_pipeline_total_failure_raises():
    provider = FakeProvider(
        responses={},
        fail={"glm-5.2", "kimi-k2.7-code", "deepseek-v4-pro", "minimax-m3",
              "nemotron-3-ultra", "qwen3.5:397b", "mistral-large-3:675b",
              "gemini-3-flash-preview"},
    )
    with pytest.raises(Exception):
        run_multiai("Frage?", config=_cfg(), provider=provider)


def test_pipeline_concat():
    provider = FakeProvider(
        responses={
            "glm-5.2": "G",
            "kimi-k2.7-code": "K",
            "deepseek-v4-pro": "D",
            "minimax-m3": "M",
            "nemotron-3-ultra": "N",
            "qwen3.5:397b": "Q",
            "mistral-large-3:675b": "ML",
            "gemini-3-flash-preview": "GF",
        }
    )
    result = run_multiai("Frage?", config=_cfg(strategy="concat"), provider=provider)
    assert result.strategy == "concat"
    assert result.used_quorum is False
    assert "K" in result.final and "G" in result.final


def test_pipeline_passes_worker_extra_body():
    provider = FakeProvider(
        responses={
            "glm-5.2": "G",
            "kimi-k2.7-code": "K",
            "deepseek-v4-pro": "D",
            "minimax-m3": "M",
            "nemotron-3-ultra": "N",
            "qwen3.5:397b": "Q",
            "mistral-large-3:675b": "ML",
            "gemini-3-flash-preview": "GF",
        },
        synth="SYNTH",
    )
    result = run_multiai("Frage?", config=_cfg(), provider=provider)

    # Worker-Calls: keine system-Message mit "Responses from models"
    worker_calls = [
        c for c in provider.calls
        if not any(
            m.get("role") == "system" and "Responses from models" in m.get("content", "")
            for m in c[1]
        )
    ]
    assert len(worker_calls) == 8
    for model, messages, kwargs in worker_calls:
        assert kwargs.get("extra_body") == {"reasoning_effort": "xhigh"}
