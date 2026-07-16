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
            "deepseek-v4-pro": "D",
            "qwen3.5:397b": "Q",
            "glm-5.2": "G",
        },
        synth="SYNTH",
    )
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 3
    assert result.strategy == "moa"
    assert result.used_quorum is False
    assert result.final == "SYNTH"
    # glm-5.2 laeuft als Worker UND als Aggregator -> 2 Calls
    glm_calls = [c for c in provider.calls if c[0] == "glm-5.2"]
    assert len(glm_calls) == 2


def test_pipeline_degradation_one_ok():
    provider = FakeProvider(
        responses={"glm-5.2": "G"},
        fail={"deepseek-v4-pro", "qwen3.5:397b"},
        synth="SYNTH",
    )
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 1
    assert result.used_quorum is True
    assert result.final == "SYNTH"


def test_pipeline_lead_fallback_zero_ok():
    # Alle Worker scheitern -> Lead antwortet allein
    provider = FakeProvider(
        responses={"glm-5.2": "Lead-Allein"},
        fail={"deepseek-v4-pro", "qwen3.5:397b"},
    )
    cfg = _cfg(worker_models=["deepseek-v4-pro", "qwen3.5:397b"])
    result = run_multiai("Frage?", config=cfg, provider=provider)
    assert result.n_ok == 0
    assert result.used_quorum is True
    assert result.final == "Lead-Allein"


def test_pipeline_total_failure_raises():
    provider = FakeProvider(
        responses={},
        fail={"deepseek-v4-pro", "qwen3.5:397b", "glm-5.2"},
    )
    with pytest.raises(Exception):
        run_multiai("Frage?", config=_cfg(), provider=provider)


def test_pipeline_concat():
    provider = FakeProvider(
        responses={
            "deepseek-v4-pro": "D",
            "qwen3.5:397b": "Q",
            "glm-5.2": "G",
        }
    )
    result = run_multiai("Frage?", config=_cfg(strategy="concat"), provider=provider)
    assert result.strategy == "concat"
    assert result.used_quorum is False
    # Concat-Output enthaelt alle drei Worker-Antworten
    assert "D" in result.final
    assert "Q" in result.final
    assert "G" in result.final


def test_pipeline_passes_worker_extra_body():
    provider = FakeProvider(
        responses={
            "deepseek-v4-pro": "D",
            "qwen3.5:397b": "Q",
            "glm-5.2": "G",
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
    assert len(worker_calls) == 3  # 3 Worker
    for model, messages, kwargs in worker_calls:
        assert kwargs.get("extra_body") == {"reasoning_effort": "xhigh"}
