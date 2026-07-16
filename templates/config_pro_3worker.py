"""
multiai/config.py — Vorlage für Ollama Cloud Pro (3 Worker)
Ersetze DEFAULT_AGGREGATOR_MODEL und DEFAULT_WORKER_MODELS nach Bedarf.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# ── Ollama Cloud Pro, 3 Worker ──────────────────────────────────────────────
DEFAULT_AGGREGATOR_MODEL = "glm-5.2"
DEFAULT_WORKER_MODELS = [
    "deepseek-v4-pro",   # DeepSeek — bestes Reasoning, Level 4
    "qwen3.5:397b",      # Qwen — 397B Parameter, General/Creative
    "glm-5.2",           # Z.ai — Flaggschiff, auch als Aggregator
]
DEFAULT_WORKER_EXTRA_BODY    = {"reasoning_effort": "xhigh"}
DEFAULT_BASE_URL             = "https://ollama.com/v1"
DEFAULT_TIMEOUT_S            = 240
DEFAULT_QUORUM_K             = 2
DEFAULT_WORKER_MAX_TOKENS    = 16384
DEFAULT_WORKER_TEMPERATURE   = 0.7
DEFAULT_AGGREGATOR_MAX_TOKENS    = 16384
DEFAULT_AGGREGATOR_TEMPERATURE   = 0.3
DEFAULT_STRATEGY             = "moa"
DEFAULT_LOG_DIR              = os.path.expanduser("~/.multiai")


@dataclass
class MultiAIConfig:
    aggregator_model: str         = DEFAULT_AGGREGATOR_MODEL
    worker_models: list[str]      = field(default_factory=lambda: list(DEFAULT_WORKER_MODELS))
    base_url: str                 = DEFAULT_BASE_URL
    timeout_s: int                = DEFAULT_TIMEOUT_S
    quorum_k: int                 = DEFAULT_QUORUM_K
    worker_max_tokens: int        = DEFAULT_WORKER_MAX_TOKENS
    worker_temperature: float     = DEFAULT_WORKER_TEMPERATURE
    aggregator_max_tokens: int    = DEFAULT_AGGREGATOR_MAX_TOKENS
    aggregator_temperature: float = DEFAULT_AGGREGATOR_TEMPERATURE
    strategy: str                 = DEFAULT_STRATEGY
    aggregator_extra_body: dict[str, Any] = field(
        default_factory=lambda: {"reasoning_effort": "xhigh"}
    )
    worker_extra_body: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_WORKER_EXTRA_BODY)
    )
    enable_logging: bool = True
    log_dir: str         = DEFAULT_LOG_DIR

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiAIConfig":
        return cls(**d)
