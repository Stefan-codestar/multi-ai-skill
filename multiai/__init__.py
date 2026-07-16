from __future__ import annotations

from .config import MultiAIConfig
from .pipeline import Result, run_multiai
from .providers import OllamaCloudProvider, ProviderError

__version__ = "0.1.0"

__all__ = ["run_multiai", "MultiAIConfig", "Result", "OllamaCloudProvider", "ProviderError"]
