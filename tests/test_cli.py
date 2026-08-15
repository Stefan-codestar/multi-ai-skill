from __future__ import annotations

import json

import pytest

from multiai.cli import main


@pytest.fixture
def stub_run(monkeypatch):
    """Faengt run_multiai ab und merkt sich Frage und Config."""
    seen = {}

    class FakeResult:
        final = "ANTWORT"
        drafts = []
        aggregator_model = "x"
        strategy = "brief"
        used_quorum = False
        n_ok = 7
        profile = "claude"
        council_size = 7
        needs_external_synthesis = True
        modelcheck_warning = ""

    def fake(question, config=None, provider=None):
        seen["question"] = question
        seen["config"] = config
        return FakeResult()

    monkeypatch.setattr("multiai.cli.run_multiai", fake)
    return seen


def test_roster_prints_both_profiles(capsys):
    assert main(["--roster"]) == 0
    out = capsys.readouterr().out
    assert "Profil: claude (Standard)" in out
    assert "Profil: vps" in out
    assert "Querdenker" in out


def test_missing_question_is_a_usage_error(capsys):
    assert main([]) == 2
    assert "Frage fehlt" in capsys.readouterr().err


def test_self_eval_rejects_an_extra_question(capsys):
    assert main(["--self-eval", "und noch was"]) == 2
    assert "keine Frage" in capsys.readouterr().err


def test_self_eval_builds_the_question_from_the_repo(stub_run, capsys):
    assert main(["--self-eval"]) == 0
    assert "Rat der Sieben" in stub_run["question"]
    assert "SKILL.md" in stub_run["question"]
    assert capsys.readouterr().out.strip() == "ANTWORT"


def test_profile_flag_selects_vps(stub_run):
    main(["Frage?", "--profile", "vps", "--strategy", "concat"])
    assert stub_run["config"].profile == "vps"
    assert stub_run["config"].aggregator_model == "glm-5.2"


def test_default_profile_is_claude(stub_run):
    main(["Frage?"])
    assert stub_run["config"].profile == "claude"
    assert stub_run["config"].strategy == "brief"


def test_models_override_shrinks_council_and_keeps_roles(stub_run):
    main(["Frage?", "--models", "a,b,c"])
    cfg = stub_run["config"]
    assert cfg.worker_models == ["a", "b", "c"]
    assert cfg.seat_roles == ["Analytiker", "Ingenieur", "Skeptiker"]


def test_lead_override_switches_aggregator_to_http(stub_run):
    main(["Frage?", "--lead", "glm-5.2", "--strategy", "moa"])
    cfg = stub_run["config"]
    assert cfg.aggregator_model == "glm-5.2"
    assert cfg.aggregator_kind == "http"


def test_moa_on_inprocess_profile_falls_back_to_brief(stub_run, capsys):
    """moa auf dem claude-Profil faellt still auf brief zurueck (mit Warnung)."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert main(["Frage?", "--profile", "claude", "--strategy", "moa"]) == 0
    cfg = stub_run["config"]
    assert cfg.strategy == "brief"  # still auf brief gefallen
    assert any("in-process" in str(x.message) for x in w)


def test_flags_reach_the_config(stub_run):
    main(["Frage?", "--max-parallel", "7", "--quorum", "2", "--timeout", "30",
          "--no-lenses", "--no-log", "--log-dir", "/tmp/x"])
    cfg = stub_run["config"]
    assert cfg.max_parallel == 7
    assert cfg.quorum_k == 2
    assert cfg.timeout_s == 30
    assert cfg.use_lenses is False
    assert cfg.enable_logging is False
    assert cfg.log_dir == "/tmp/x"


def test_json_output_reports_council_state(stub_run, capsys):
    assert main(["Frage?", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "claude"
    assert payload["needs_external_synthesis"] is True
    assert payload["council_size"] == 7


def test_stream_on_inprocess_profile_warns(stub_run, capsys):
    main(["Frage?", "--stream", "--json"])
    assert "keine Wirkung" in capsys.readouterr().err


def test_pipeline_error_becomes_exit_1(monkeypatch, capsys):
    def boom(*_a, **_kw):
        raise RuntimeError("Ollama weg")

    monkeypatch.setattr("multiai.cli.run_multiai", boom)
    assert main(["Frage?"]) == 1
    assert "Ollama weg" in capsys.readouterr().err
