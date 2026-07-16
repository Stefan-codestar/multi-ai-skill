from __future__ import annotations

import datetime
import json
import os

from multiai.config import DEFAULT_WORKER_MODELS
from multiai.modelcheck import is_due, run_check
from multiai.providers import _CLINEPASS_TO_OPENROUTER


# --- is_due ---

def test_is_due_none():
    assert is_due(None, datetime.date(2026, 7, 14)) is True


def test_is_due_same_week():
    assert is_due("2026-07-14", datetime.date(2026, 7, 16)) is False


def test_is_due_prev_week():
    assert is_due("2026-07-07", datetime.date(2026, 7, 14)) is True


def test_is_due_year_boundary():
    # 2026-12-28 = ISO-Woche 53/2026, 2027-01-04 = ISO-Woche 1/2027
    assert is_due("2026-12-28", datetime.date(2027, 1, 4)) is True


def test_is_due_unparseable():
    assert is_due("kaputt", datetime.date(2026, 7, 14)) is True


# --- run_check ---

def test_run_check_not_due(tmp_path):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)
    state = {"last_check": today.isoformat(), "ollama_models": [], "openrouter_mapped_ok": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is False
    assert "nicht faellig" in report


def test_run_check_force_same_week(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)
    state = {"last_check": today.isoformat(), "ollama_models": [], "openrouter_mapped_ok": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, _report = run_check(state_path=state_path, force=True, today=today)
    assert ran is True


def test_run_check_first_run(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    workers = ["glm-5.2", "kimi-k2.7-code"]
    monkeypatch.setattr("multiai.modelcheck.DEFAULT_WORKER_MODELS", workers)
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(workers))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert report.startswith("BASELINE ERSTELLT")
    assert os.path.isfile(state_path)


def test_run_check_second_run_diff(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"altes-modell", "glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())
    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"neues-modell", "glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert "+ neues-modell" in report
    assert "- altes-modell" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")


def test_run_check_missing_worker(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "WARNUNG" in report
    assert "nicht im Ollama-Katalog" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")


def test_run_check_dead_openrouter_mapping(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(DEFAULT_WORKER_MODELS))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "INFO" in report
    assert "weiterhin tot" in report
    assert report.startswith("BASELINE ERSTELLT")


def test_run_check_mapping_newly_dead(tmp_path, monkeypatch):
    """Mapping war OK, ist jetzt tot -> WARNUNG, AENDERUNGEN GEFUNDEN."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    workers = ["glm-5.2"]
    monkeypatch.setattr("multiai.modelcheck.DEFAULT_WORKER_MODELS", workers)
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", frozenset({"cline-pass/glm-5.2"}))
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", {"cline-pass/glm-5.2": "vendor/glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(workers))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: {"vendor/glm-5.2"})

    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert "WARNUNG" in report
    assert "neu tot" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")


def test_run_check_mapping_stays_dead(tmp_path, monkeypatch):
    """Mapping war tot, bleibt tot -> INFO, KEINE AENDERUNGEN."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    workers = ["glm-5.2"]
    monkeypatch.setattr("multiai.modelcheck.DEFAULT_WORKER_MODELS", workers)
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", frozenset({"cline-pass/glm-5.2"}))
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", {"cline-pass/glm-5.2": "vendor/glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(workers))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert "INFO" in report
    assert "weiterhin tot" in report
    assert report.startswith("KEINE AENDERUNGEN")


def test_run_check_atomic_save(tmp_path, monkeypatch):
    """State wird atomar geschrieben — keine .tmp-Datei bleibt zurueck."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    run_check(state_path=state_path, today=today)

    assert os.path.isfile(state_path)
    assert not os.path.isfile(state_path + ".tmp")


def test_run_check_fetch_error(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    def boom():
        raise RuntimeError("Verbindungsfehler")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", boom)
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: set())

    state = {"last_check": "2026-07-07", "ollama_models": ["x"], "openrouter_mapped_ok": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "FEHLER" in report

    # State darf nicht aktualisiert worden sein
    with open(state_path) as f:
        new_state = json.load(f)
    assert new_state["last_check"] == "2026-07-07"


def test_run_check_no_changes(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    # Mock: alle Worker haben ClinePass + OpenRouter-Mapping, alle OK
    fake_cline = {f"cline-pass/{w}" for w in DEFAULT_WORKER_MODELS}
    fake_mapping = {f"cline-pass/{w}": f"vendor/{w}" for w in DEFAULT_WORKER_MODELS}
    fake_targets = set(fake_mapping.values())

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(DEFAULT_WORKER_MODELS))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: fake_targets)
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", fake_cline)
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", fake_mapping)

    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert report.startswith("KEINE AENDERUNGEN")


def test_run_check_gaps_stable(tmp_path, monkeypatch):
    """Gleicher Luecken-Stand -> KEINE AENDERUNGEN."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    workers = ["glm-5.2", "kimi-k2.7-code"]
    monkeypatch.setattr("multiai.modelcheck.DEFAULT_WORKER_MODELS", workers)
    # Nur glm-5.2 hat Fallback; kimi ist Luecke
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", frozenset({"cline-pass/glm-5.2"}))
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", {"cline-pass/glm-5.2": "vendor/glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(workers))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: {"vendor/glm-5.2"})

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "LUECKE" in report

    today2 = datetime.date(2026, 7, 21)
    ran2, report2 = run_check(state_path=state_path, today=today2)
    assert ran2 is True
    assert "LUECKE" in report2
    assert report2.startswith("KEINE AENDERUNGEN")


def test_run_check_gap_new(tmp_path, monkeypatch):
    """Neue Luecke -> AENDERUNGEN GEFUNDEN."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    workers = ["glm-5.2", "kimi-k2.7-code"]
    monkeypatch.setattr("multiai.modelcheck.DEFAULT_WORKER_MODELS", workers)
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", frozenset({
        "cline-pass/glm-5.2",
        "cline-pass/kimi-k2.7-code",
    }))
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", {
        "cline-pass/glm-5.2": "vendor/glm-5.2",
        "cline-pass/kimi-k2.7-code": "vendor/kimi",
    })
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(workers))
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: {"vendor/glm-5.2", "vendor/kimi"})

    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    # kimi verliert beide Fallback-Tiers
    monkeypatch.setattr("multiai.modelcheck.CLINE_PASS_MODELS", frozenset({"cline-pass/glm-5.2"}))
    monkeypatch.setattr("multiai.modelcheck._CLINEPASS_TO_OPENROUTER", {"cline-pass/glm-5.2": "vendor/glm-5.2"})
    monkeypatch.setattr("multiai.modelcheck.fetch_openrouter_models", lambda: {"vendor/glm-5.2"})

    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert "LUECKE (neu)" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")
