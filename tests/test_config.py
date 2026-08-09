from __future__ import annotations

import pytest

from multiai.config import MultiAIConfig
from multiai.profiles import COUNCIL_SIZE, get_profile


def test_default_config_is_claude_profile():
    c = MultiAIConfig()
    assert c.profile == "claude"
    assert c.aggregator_model == "claude-opus-5"
    assert c.aggregator_kind == "inprocess"
    assert c.strategy == "brief"
    assert c.council_size == COUNCIL_SIZE


def test_vps_profile_aggregates_over_http_with_glm():
    c = MultiAIConfig.from_profile("vps")
    assert c.aggregator_model == "glm-5.2"
    assert c.aggregator_kind == "http"
    assert c.strategy == "moa"
    assert c.base_url == "https://ollama.com/v1"


def test_both_profiles_have_seven_seats_with_roles_and_lenses():
    for name in ("claude", "vps"):
        c = MultiAIConfig.from_profile(name)
        assert len(c.worker_models) == COUNCIL_SIZE
        assert len(c.seat_roles) == COUNCIL_SIZE
        assert len(c.seat_lenses) == COUNCIL_SIZE
        assert all(lens.strip() for lens in c.seat_lenses)


def test_aggregator_never_sits_on_the_council():
    """Self-Bias-Schutz: der Aggregator darf keinen eigenen Entwurf bewerten."""
    for name in ("claude", "vps"):
        profile = get_profile(name)
        assert profile.aggregator_model not in profile.worker_models


def test_runtime_defaults():
    c = MultiAIConfig()
    assert c.timeout_s == 240
    assert c.quorum_k == 4                 # Mehrheit von sieben
    assert c.max_parallel == 3             # Ollama Cloud Pro
    assert c.worker_max_tokens == 16384
    assert c.worker_temperature == 0.7
    assert c.aggregator_max_tokens == 16384
    assert c.aggregator_temperature == 0.3
    assert c.worker_extra_body == {"reasoning_effort": "xhigh"}
    assert c.use_lenses is True
    assert c.enable_logging is True
    assert isinstance(c.log_dir, str) and c.log_dir


def test_from_dict_override():
    c = MultiAIConfig.from_dict({"strategy": "concat", "quorum_k": 3, "enable_logging": False})
    assert c.strategy == "concat"
    assert c.quorum_k == 3
    assert c.enable_logging is False


def test_from_dict_with_profile_key():
    c = MultiAIConfig.from_dict({"profile": "vps", "quorum_k": 2})
    assert c.profile == "vps"
    assert c.aggregator_model == "glm-5.2"
    assert c.quorum_k == 2


def test_from_dict_rejects_unknown_key():
    with pytest.raises(TypeError):
        MultiAIConfig.from_dict({"gibt_es_nicht": 1})


def test_inprocess_aggregator_falls_back_to_brief_on_moa():
    """Opus 5 laeuft nicht ueber den Provider — moa faellt still auf brief zurueck."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        c = MultiAIConfig.from_profile("claude", strategy="moa")
    assert c.strategy == "brief"
    assert len(w) == 1
    assert "in-process" in str(w[0].message)


def test_inprocess_aggregator_runs_moa_after_lead_override():
    c = MultiAIConfig.from_profile("claude", aggregator_model="glm-5.2",
                                   aggregator_kind="http", strategy="moa")
    assert c.strategy == "moa"


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError, match="Unbekannte Strategie"):
        MultiAIConfig.from_dict({"strategy": "telepathie"})


def test_seat_list_length_mismatch_rejected():
    with pytest.raises(ValueError, match="seat_lenses"):
        MultiAIConfig.from_dict({"worker_models": ["a", "b"], "seat_roles": ["x", "y"]})


def test_models_override_keeps_roles_and_shrinks_council():
    c = MultiAIConfig.from_profile("vps", worker_models=["a", "b"])
    assert c.worker_models == ["a", "b"]
    assert c.seat_roles == ["Analytiker", "Ingenieur"]
    assert c.council_size == 2


def test_lens_disabled_returns_none():
    c = MultiAIConfig.from_profile("vps", use_lenses=False)
    assert c.lens_for(0) is None
    assert c.role_for(0) == "Analytiker"


def test_mutable_defaults_not_shared():
    c1, c2 = MultiAIConfig(), MultiAIConfig()
    assert c1.worker_models is not c2.worker_models
    assert c1.worker_extra_body is not c2.worker_extra_body
    c1.worker_models.append("extra")
    c1.worker_extra_body["test"] = True
    assert "extra" not in c2.worker_models
    assert "test" not in c2.worker_extra_body
