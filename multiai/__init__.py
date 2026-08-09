from __future__ import annotations

from .config import MultiAIConfig
from .council import render_brief, render_roster, render_seats
from .pipeline import Result, run_multiai, run_multiai_stream
from .profiles import (
    COUNCIL_SIZE,
    PROFILES,
    Profile,
    Seat,
    diversity_report,
    get_profile,
)
from .providers import OllamaCloudProvider, ProviderError

__version__ = "1.0.0"

__all__ = [
    "run_multiai",
    "run_multiai_stream",
    "MultiAIConfig",
    "Result",
    "OllamaCloudProvider",
    "ProviderError",
    "Profile",
    "Seat",
    "PROFILES",
    "COUNCIL_SIZE",
    "get_profile",
    "diversity_report",
    "render_brief",
    "render_seats",
    "render_roster",
]
