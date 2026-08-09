from __future__ import annotations

import threading

import pytest

from multiai.aggregate import SYNTH_MARKER
from multiai.config import MultiAIConfig
from multiai.pipeline import run_multiai, run_multiai_stream
from multiai.profiles import get_profile

VPS_SEATS = get_profile("vps").worker_models
CLAUDE_SEATS = get_profile("claude").worker_models


def _is_synth(messages) -> bool:
    return any(
        m.get("role") == "system" and SYNTH_MARKER in m.get("content", "")
        for m in messages
    )


class FakeProvider:
    """Trennt Synthese-Calls (System-Prompt traegt den Marker) von Sitz-Calls."""

    def __init__(self, responses=None, synth="SYNTH", fail=None):
        self.responses = dict(responses or {})
        self.synth = synth
        self.fail = set(fail or [])
        self.calls = []
        self._lock = threading.Lock()

    def complete(self, model, messages, **kwargs):
        with self._lock:
            self.calls.append((model, messages, kwargs))
        if _is_synth(messages):
            return self.synth
        if model in self.fail:
            raise RuntimeError(f"{model} down")
        if model in self.responses:
            return self.responses[model]
        raise RuntimeError(f"{model} unknown")

    def stream_complete(self, model, messages, **kwargs):
        yield self.complete(model, messages, **kwargs)

    @property
    def seat_calls(self):
        return [c for c in self.calls if not _is_synth(c[1])]

    @property
    def synth_calls(self):
        return [c for c in self.calls if _is_synth(c[1])]


def _all_seats(models=VPS_SEATS):
    return {m: m[:2].upper() for m in models}


def _cfg(profile="vps", **kw):
    kw.setdefault("enable_logging", False)
    return MultiAIConfig.from_profile(profile, **kw)


# ── moa: Aggregator laeuft ueber HTTP ──────────────────────────────────────

def test_full_council_synthesises():
    provider = FakeProvider(responses=_all_seats())
    result = run_multiai("Frage?", config=_cfg(quorum_k=7), provider=provider)
    assert result.n_ok == 7
    assert result.council_size == 7
    assert result.profile == "vps"
    assert result.used_quorum is False
    assert result.final == "SYNTH"
    assert result.needs_external_synthesis is False
    assert len(provider.seat_calls) == 7
    assert len(provider.synth_calls) == 1
    assert provider.synth_calls[0][0] == "glm-5.2"


def test_aggregator_does_not_take_a_seat():
    provider = FakeProvider(responses=_all_seats())
    run_multiai("Frage?", config=_cfg(), provider=provider)
    assert all(model != "glm-5.2" for model, _m, _k in provider.seat_calls)


def test_quorum_flag_set_below_majority():
    """Vier von sieben ist Quorum; drei ist Degradation."""
    ok = VPS_SEATS[:3]
    provider = FakeProvider(responses={m: "X" for m in ok}, fail=set(VPS_SEATS[3:]))
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 3
    assert result.used_quorum is True
    assert result.final == "SYNTH"


def test_quorum_flag_clear_at_exactly_four():
    ok = VPS_SEATS[:4]
    provider = FakeProvider(responses={m: "X" for m in ok}, fail=set(VPS_SEATS[4:]))
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 4
    assert result.used_quorum is False


def test_empty_council_falls_back_to_aggregator_alone():
    provider = FakeProvider(responses={"glm-5.2": "Allein"}, fail=set(VPS_SEATS))
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert result.n_ok == 0
    assert result.used_quorum is True
    assert result.final == "Allein"


def test_aggregator_crash_falls_back_to_direct_answer():
    """Aggregator crasht (HTTP-Fehler) -> Fallback: Aggregator antwortet allein ohne Rat-Beitraege."""
    class SynthCrashProvider(FakeProvider):
        def complete(self, model, messages, **kwargs):
            if _is_synth(messages):
                raise RuntimeError("Aggregator 500")
            return super().complete(model, messages, **kwargs)

    provider = SynthCrashProvider(
        responses={**_all_seats(), "glm-5.2": "Direkte Antwort"}
    )
    result = run_multiai("Frage?", config=_cfg(quorum_k=7), provider=provider)
    assert result.n_ok == 7
    assert result.strategy == "moa"
    assert "Aggregator-Fallback" in result.final
    assert "Direkte Antwort" in result.final
    assert result.needs_external_synthesis is False


def test_total_failure_raises():
    provider = FakeProvider(responses={}, fail=set(VPS_SEATS) | {"glm-5.2"})
    with pytest.raises(Exception):
        run_multiai("Frage?", config=_cfg(), provider=provider)


# ── Rollen-Prompts ─────────────────────────────────────────────────────────

def test_each_seat_gets_its_own_lens():
    provider = FakeProvider(responses=_all_seats())
    run_multiai("Frage?", config=_cfg(quorum_k=7), provider=provider)
    systems = [
        next(m["content"] for m in messages if m["role"] == "system")
        for _model, messages, _kw in provider.seat_calls
    ]
    assert len(systems) == 7
    assert len(set(systems)) == 7          # kein Sitz teilt seine Rolle
    assert any("SKEPTIKER" in s for s in systems)
    assert any("QUERDENKER" in s for s in systems)


def test_no_lenses_sends_no_system_message():
    provider = FakeProvider(responses=_all_seats())
    run_multiai("Frage?", config=_cfg(use_lenses=False), provider=provider)
    for _model, messages, _kw in provider.seat_calls:
        assert all(m["role"] != "system" for m in messages)


def test_seat_drafts_carry_role_and_position():
    provider = FakeProvider(responses=_all_seats())
    result = run_multiai("Frage?", config=_cfg(), provider=provider)
    assert [d.seat for d in result.drafts] == [1, 2, 3, 4, 5, 6, 7]
    assert result.drafts[2].role == "Skeptiker"
    assert result.drafts[2].label == "Skeptiker (nemotron-3-ultra)"


def test_worker_extra_body_reaches_every_seat():
    provider = FakeProvider(responses=_all_seats())
    run_multiai("Frage?", config=_cfg(), provider=provider)
    from multiai.council import ROLE_EFFORT
    expected_efforts = set(ROLE_EFFORT.values())
    efforts_seen = set()
    for _model, _messages, kwargs in provider.seat_calls:
        effort = kwargs.get("extra_body", {}).get("reasoning_effort")
        assert effort in expected_efforts
        efforts_seen.add(effort)
    assert efforts_seen == expected_efforts


def test_max_parallel_limits_concurrency():
    """Ollama Cloud Pro haelt nur drei Modelle gleichzeitig — mehr darf nicht starten."""
    peak = 0
    active = 0
    lock = threading.Lock()
    gate = threading.Barrier(3, timeout=5)

    class CountingProvider(FakeProvider):
        def complete(self, model, messages, **kwargs):
            nonlocal peak, active
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                gate.wait()          # blockiert, bis drei Sitze gleichzeitig laufen
            except threading.BrokenBarrierError:
                pass
            with lock:
                active -= 1
            return super().complete(model, messages, **kwargs)

    provider = CountingProvider(responses=_all_seats())
    run_multiai("Frage?", config=_cfg(max_parallel=3), provider=provider)
    assert peak == 3


# ── concat ─────────────────────────────────────────────────────────────────

def test_concat_returns_all_contributions_unsynthesised():
    provider = FakeProvider(responses=_all_seats())
    result = run_multiai("Frage?", config=_cfg(strategy="concat"), provider=provider)
    assert result.strategy == "concat"
    assert provider.synth_calls == []
    assert "Analytiker (deepseek-v4-pro)" in result.final
    assert "Querdenker (command-r-plus)" in result.final


# ── brief: Claude Code ist der Aggregator ──────────────────────────────────

def test_brief_returns_instruction_without_calling_an_aggregator():
    provider = FakeProvider(responses=_all_seats(CLAUDE_SEATS))
    result = run_multiai("Frage?", config=_cfg("claude", quorum_k=7), provider=provider)
    assert result.strategy == "brief"
    assert result.needs_external_synthesis is True
    assert provider.synth_calls == []          # kein HTTP-Aggregator
    assert len(provider.seat_calls) == 7
    assert "SYNTHESE-AUFTRAG" in result.final
    assert "Frage?" in result.final


def test_brief_lists_failed_seats():
    provider = FakeProvider(
        responses={CLAUDE_SEATS[0]: "A"},
        fail=set(CLAUDE_SEATS[1:]),
    )
    result = run_multiai("Frage?", config=_cfg("claude"), provider=provider)
    assert "Nicht erschienene Sitze" in result.final
    assert result.used_quorum is True


def test_brief_with_empty_council_tells_claude_to_answer_itself():
    provider = FakeProvider(responses={}, fail=set(CLAUDE_SEATS))
    result = run_multiai("Frage?", config=_cfg("claude"), provider=provider)
    assert result.n_ok == 0
    assert "KEIN BEITRAG ERHALTEN" in result.final
    assert "--strategy seats" in result.final


# ── seats: Solo-Rat, kein Netz ─────────────────────────────────────────────

def test_seats_strategy_makes_no_provider_calls():
    provider = FakeProvider(responses={})
    result = run_multiai("Frage?", config=_cfg("claude", strategy="seats"),
                         provider=provider)
    assert provider.calls == []
    assert result.n_ok == 0
    assert result.needs_external_synthesis is True
    assert "SOLO-MODUS" in result.final
    assert result.final.count("### Sitz ") == 7


def test_seats_strategy_works_without_a_provider_at_all():
    result = run_multiai("Frage?", config=_cfg("claude", strategy="seats"))
    assert "SOLO-MODUS" in result.final


# ── Streaming ──────────────────────────────────────────────────────────────

def test_stream_yields_synthesis_for_http_aggregator():
    provider = FakeProvider(responses=_all_seats())
    chunks = list(run_multiai_stream("Frage?", config=_cfg(), provider=provider))
    assert "".join(chunks) == "SYNTH"


def test_stream_falls_back_to_single_chunk_for_brief():
    provider = FakeProvider(responses=_all_seats(CLAUDE_SEATS))
    chunks = list(run_multiai_stream("Frage?", config=_cfg("claude"), provider=provider))
    assert len(chunks) == 1
    assert "SYNTHESE-AUFTRAG" in chunks[0]


def test_stream_seats_needs_no_provider():
    chunks = list(run_multiai_stream("Frage?", config=_cfg("claude", strategy="seats")))
    assert "SOLO-MODUS" in "".join(chunks)


# ── Logging ────────────────────────────────────────────────────────────────

def test_run_log_records_profile_and_roles(tmp_path):
    import json

    provider = FakeProvider(responses=_all_seats())
    cfg = _cfg(enable_logging=True, log_dir=str(tmp_path), quorum_k=7)
    run_multiai("Frage?", config=cfg, provider=provider)

    lines = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["profile"] == "vps"
    assert record["n_ok"] == 7
    assert [d["role"] for d in record["drafts"]][:2] == ["Analytiker", "Ingenieur"]


def test_logging_failure_never_breaks_the_answer(tmp_path, monkeypatch):
    provider = FakeProvider(responses=_all_seats())

    def boom(*_a, **_kw):
        raise OSError("Platte voll")

    monkeypatch.setattr("multiai.pipeline.log_run", boom)
    result = run_multiai("Frage?", config=_cfg(enable_logging=True,
                                               log_dir=str(tmp_path)),
                         provider=provider)
    assert result.final == "SYNTH"


def test_missing_key_degrades_to_the_solo_hint(monkeypatch):
    """Ohne Key faellt jeder Sitz einzeln aus — der Lauf stirbt nicht."""
    from multiai.providers import ProviderError

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        "multiai.providers._load_ollama_key",
        lambda: (_ for _ in ()).throw(ProviderError("", "OLLAMA_API_KEY nicht gefunden")),
    )
    result = run_multiai("Frage?", config=_cfg("claude"))
    assert result.n_ok == 0
    assert len(result.drafts) == 7
    assert "KEIN BEITRAG ERHALTEN" in result.final
    assert "--strategy seats" in result.final
