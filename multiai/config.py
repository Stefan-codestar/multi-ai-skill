from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .profiles import (
    DEFAULT_PROFILE_NAME,
    Profile,
    get_profile,
    with_models,
)

# ── Laufzeit-Defaults (profilunabhaengig) ──────────────────────────────────
DEFAULT_TIMEOUT_S              = 240   # 4 Minuten — Thinking-Modelle brauchen Zeit
DEFAULT_QUORUM_K               = 4     # Mehrheit des Rats (4 von 7)
DEFAULT_WORKER_MAX_TOKENS      = 16384
DEFAULT_WORKER_TEMPERATURE     = 0.7
DEFAULT_AGGREGATOR_MAX_TOKENS  = 16384
DEFAULT_AGGREGATOR_TEMPERATURE = 0.3
DEFAULT_WORKER_EXTRA_BODY      = {"reasoning_effort": "xhigh"}
DEFAULT_LOG_DIR                = os.path.expanduser("~/.multiai")

# Rueckwaertskompatible Aliase — der Rat des Standardprofils.
_DEFAULT_PROFILE       = get_profile(DEFAULT_PROFILE_NAME)
DEFAULT_BASE_URL       = _DEFAULT_PROFILE.base_url
DEFAULT_AGGREGATOR_MODEL = _DEFAULT_PROFILE.aggregator_model
DEFAULT_WORKER_MODELS  = _DEFAULT_PROFILE.worker_models
DEFAULT_STRATEGY       = _DEFAULT_PROFILE.default_strategy

VALID_STRATEGIES = ("moa", "concat", "brief", "seats")


@dataclass
class MultiAIConfig:
    """Flache, serialisierbare Laufzeit-Konfiguration eines Rats-Laufs.

    ``worker_models``, ``seat_roles`` und ``seat_lenses`` sind parallele Listen —
    Index i beschreibt Sitz i. Gebaut wird das normalerweise ueber
    :meth:`from_profile`; ``from_dict`` erlaubt punktuelle Overrides.
    """

    profile: str                  = DEFAULT_PROFILE_NAME
    aggregator_model: str         = _DEFAULT_PROFILE.aggregator_model
    aggregator_kind: str          = _DEFAULT_PROFILE.aggregator_kind
    worker_models: list[str]      = field(
        default_factory=lambda: list(_DEFAULT_PROFILE.worker_models)
    )
    seat_roles: list[str]         = field(
        default_factory=lambda: [s.role for s in _DEFAULT_PROFILE.seats]
    )
    seat_lenses: list[str]        = field(
        default_factory=lambda: list(_DEFAULT_PROFILE.lenses)
    )
    base_url: str                 = _DEFAULT_PROFILE.base_url
    timeout_s: int                = DEFAULT_TIMEOUT_S
    quorum_k: int                 = DEFAULT_QUORUM_K
    max_parallel: int             = _DEFAULT_PROFILE.max_parallel
    worker_max_tokens: int        = DEFAULT_WORKER_MAX_TOKENS
    worker_temperature: float     = DEFAULT_WORKER_TEMPERATURE
    aggregator_max_tokens: int    = DEFAULT_AGGREGATOR_MAX_TOKENS
    aggregator_temperature: float = DEFAULT_AGGREGATOR_TEMPERATURE
    strategy: str                 = _DEFAULT_PROFILE.default_strategy
    use_lenses: bool              = True
    aggregator_extra_body: dict[str, Any] = field(
        default_factory=lambda: {"reasoning_effort": "xhigh"}
    )
    worker_extra_body: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_WORKER_EXTRA_BODY)
    )
    enable_logging: bool = True
    log_dir: str         = DEFAULT_LOG_DIR

    # ── Konstruktion ───────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiAIConfig":
        """Baut eine Config aus einem Override-Dict.

        Enthaelt das Dict ``profile``, wird zuerst das Profil geladen und die
        restlichen Schluessel werden darauf angewendet.
        """
        d = dict(d)
        profile_name = d.pop("profile", None)
        if profile_name is None:
            cfg = cls()
        else:
            cfg = cls.from_profile(get_profile(profile_name))
        for key, value in d.items():
            if not hasattr(cfg, key):
                raise TypeError(f"Unbekannter Config-Schluessel: {key}")
            setattr(cfg, key, value)
        cfg.validate()
        return cfg

    @classmethod
    def from_profile(cls, profile: Profile | str, **overrides: Any) -> "MultiAIConfig":
        """Baut eine Config aus einem Profil (Name oder Objekt) plus Overrides."""
        if isinstance(profile, str):
            profile = get_profile(profile)
        models = overrides.pop("worker_models", None)
        if models:
            profile = with_models(profile, list(models))
        cfg = cls(
            profile=profile.name,
            aggregator_model=profile.aggregator_model,
            aggregator_kind=profile.aggregator_kind,
            worker_models=list(profile.worker_models),
            seat_roles=[s.role for s in profile.seats],
            seat_lenses=list(profile.lenses),
            base_url=profile.base_url,
            max_parallel=profile.max_parallel,
            strategy=profile.default_strategy,
        )
        for key, value in overrides.items():
            if not hasattr(cfg, key):
                raise TypeError(f"Unbekannter Config-Schluessel: {key}")
            setattr(cfg, key, value)
        cfg.validate()
        return cfg

    # ── Konsistenz ─────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Prueft die Invarianten, auf die sich die Pipeline verlaesst."""
        if self.strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"Unbekannte Strategie: {self.strategy!r}. "
                f"Erlaubt: {', '.join(VALID_STRATEGIES)}"
            )
        n = len(self.worker_models)
        if self.seat_roles and len(self.seat_roles) != n:
            raise ValueError(
                f"seat_roles ({len(self.seat_roles)}) passt nicht zu "
                f"worker_models ({n})"
            )
        if self.seat_lenses and len(self.seat_lenses) != n:
            raise ValueError(
                f"seat_lenses ({len(self.seat_lenses)}) passt nicht zu "
                f"worker_models ({n})"
            )
        if self.aggregator_kind == "inprocess" and self.strategy == "moa":
            import warnings
            warnings.warn(
                f"Profil {self.profile!r} aggregiert in-process "
                f"({self.aggregator_model}) und kann 'moa' nicht selbst "
                f"ausfuehren. Falle auf 'brief' zurueck — der Synthese-Auftrag "
                f"geht an Claude Code.",
                stacklevel=2,
            )
            self.strategy = "brief"
        if self.max_parallel < 1:
            raise ValueError("max_parallel muss >= 1 sein")
        if self.quorum_k < 1:
            raise ValueError("quorum_k muss >= 1 sein")

    # ── Ableitungen ────────────────────────────────────────────────────────

    def lens_for(self, index: int) -> str | None:
        """Lens-System-Prompt fuer Sitz ``index``; None wenn Lenses aus sind."""
        if not self.use_lenses or not self.seat_lenses:
            return None
        if index >= len(self.seat_lenses):
            return None
        return self.seat_lenses[index]

    def role_for(self, index: int) -> str:
        """Rollenname fuer Sitz ``index``; faellt auf den Modellnamen zurueck."""
        if self.seat_roles and index < len(self.seat_roles):
            return self.seat_roles[index]
        return self.worker_models[index]

    @property
    def council_size(self) -> int:
        return len(self.worker_models)
