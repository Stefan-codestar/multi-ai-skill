from __future__ import annotations

from multiai.config import MultiAIConfig


def test_defaults():
    c = MultiAIConfig()
    assert c.aggregator_model == "glm-5.2"
    assert c.worker_models == [
        "deepseek-v4-pro",
        "nemotron-3-ultra",
        "mistral-large-3:675b",
    ]
    assert c.base_url == "https://ollama.com/v1"
    assert c.timeout_s == 240
    assert c.quorum_k == 2
    assert c.worker_max_tokens == 16384
    assert c.worker_temperature == 0.7
    assert c.aggregator_max_tokens == 16384
    assert c.aggregator_temperature == 0.3
    assert c.strategy == "moa"
    assert c.aggregator_extra_body == {"reasoning_effort": "xhigh"}
    assert c.worker_extra_body == {"reasoning_effort": "xhigh"}
    assert c.enable_logging is True
    assert isinstance(c.log_dir, str) and c.log_dir


def test_from_dict_override():
    c = MultiAIConfig.from_dict({"strategy": "concat", "quorum_k": 3, "enable_logging": False})
    assert c.strategy == "concat"
    assert c.quorum_k == 3
    assert c.enable_logging is False
    assert c.aggregator_model == "glm-5.2"


def test_worker_models_not_shared():
    c1 = MultiAIConfig()
    c2 = MultiAIConfig()
    assert c1.worker_models is not c2.worker_models
    c1.worker_models.append("extra")
    assert "extra" not in c2.worker_models


def test_worker_extra_body_not_shared():
    c1 = MultiAIConfig()
    c2 = MultiAIConfig()
    assert c1.worker_extra_body is not c2.worker_extra_body
    c1.worker_extra_body["test"] = True
    assert "test" not in c2.worker_extra_body
