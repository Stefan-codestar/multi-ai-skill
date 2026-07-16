from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import Any


DEFAULT_AGGREGATOR_MODEL = "glm-5.2"
DEFAULT_WORKER_MODELS = [
    "glm-5.2",                    # Z.ai — 1M ctx, Flagship coding, deep reasoning
    "kimi-k2.7-code",             # Moonshot — 262K ctx, coding tasks, vision-capable
    "deepseek-v4-pro",            # DeepSeek — 1M ctx, heavy reasoning, large changes
    "minimax-m3",                 # MiniMax — 512K ctx, general coding
    "nemotron-3-ultra",           # NVIDIA — large reasoning, science/code
    "qwen3.5:397b",               # Qwen — 397B params, general/creative
    "mistral-large-3:675b",       # Mistral — 675B params, large context
    "gemini-3-flash-preview",     # Google — fast preview, multimodal
]
DEFAULT_WORKER_EXTRA_BODY = {"reasoning_effort": "xhigh"}
DEFAULT_BASE_URL = "https://ollama.com/v1"
DEFAULT_TIMEOUT_S = 240
DEFAULT_QUORUM_K = 2
DEFAULT_WORKER_MAX_TOKENS = 32768
DEFAULT_WORKER_TEMPERATURE = 0.7
DEFAULT_AGGREGATOR_MAX_TOKENS = 32768
DEFAULT_AGGREGATOR_TEMPERATURE = 0.3
DEFAULT_STRATEGY = "moa"
DEFAULT_LOG_DIR = os.path.expanduser("~/.multiai")


@dataclass
class MultiAIConfig:
    aggregator_model: str = DEFAULT_AGGREGATOR_MODEL
    worker_models: list[str] = field(default_factory=lambda: list(DEFAULT_WORKER_MODELS))
    base_url: str = DEFAULT_BASE_URL
    timeout_s: int = DEFAULT_TIMEOUT_S
    quorum_k: int = DEFAULT_QUORUM_K
    worker_max_tokens: int = DEFAULT_WORKER_MAX_TOKENS
    worker_temperature: float = DEFAULT_WORKER_TEMPERATURE
    aggregator_max_tokens: int = DEFAULT_AGGREGATOR_MAX_TOKENS
    aggregator_temperature: float = DEFAULT_AGGREGATOR_TEMPERATURE
    strategy: str = DEFAULT_STRATEGY
    aggregator_extra_body: dict[str, Any] = field(default_factory=lambda: {"reasoning_effort": "xhigh"})
    worker_extra_body: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_WORKER_EXTRA_BODY))
    enable_logging: bool = True
    log_dir: str = DEFAULT_LOG_DIR

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiAIConfig":
        return cls(**d)
