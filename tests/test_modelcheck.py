from __future__ import annotations

import datetime
import json
import os

from multiai.modelcheck import WATCHED_MODELS, is_due, run_check


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
    state = {"last_check": today.isoformat(), "ollama_models": [], "fallback_gaps": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is False
    assert "nicht faellig" in report


def test_run_check_force_same_week(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)
    state = {"last_check": today.isoformat(), "ollama_models": [], "fallback_gaps": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())

    ran, _report = run_check(state_path=state_path, force=True, today=today)
    assert ran is True


def test_run_check_first_run(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    watched = ["deepseek-v4-pro:preview", "nemotron-3-ultra", "mistral-large-3:675b"]
    monkeypatch.setattr("multiai.modelcheck.WATCHED_MODELS", watched)
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(watched))

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert report.startswith("BASELINE ERSTELLT")
    assert os.path.isfile(state_path)


def test_run_check_second_run_diff(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"altes-modell", "glm-5.2"})
    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"neues-modell", "glm-5.2"})

    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert "+ neues-modell" in report
    assert "- altes-modell" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")


def test_run_check_missing_worker(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    # Ollama kennt keines der konfigurierten Worker-Modelle
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "WARNUNG" in report
    assert "nicht im Ollama-Katalog" in report
    assert report.startswith("AENDERUNGEN GEFUNDEN")


def test_run_check_no_changes(tmp_path, monkeypatch):
    """Zweiter Lauf mit gleichen Modellen -> KEINE AENDERUNGEN."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set(WATCHED_MODELS))
    run_check(state_path=state_path, today=today)

    today2 = datetime.date(2026, 7, 21)
    ran, report = run_check(state_path=state_path, today=today2)
    assert ran is True
    assert report.startswith("KEINE AENDERUNGEN")


def test_run_check_atomic_save(tmp_path, monkeypatch):
    """State wird atomar geschrieben — keine .tmp-Datei bleibt zurueck."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: set())

    run_check(state_path=state_path, today=today)

    assert os.path.isfile(state_path)
    assert not os.path.isfile(state_path + ".tmp")


def test_run_check_fetch_error(tmp_path, monkeypatch):
    """Fetch-Fehler -> AENDERUNGEN GEFUNDEN + FEHLER, State unveraendert."""
    state_path = str(tmp_path / "state.json")
    today = datetime.date(2026, 7, 14)

    def boom():
        raise RuntimeError("Verbindungsfehler")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", boom)

    state = {"last_check": "2026-07-07", "ollama_models": ["x"], "fallback_gaps": []}
    with open(state_path, "w") as f:
        json.dump(state, f)

    ran, report = run_check(state_path=state_path, today=today)
    assert ran is True
    assert "FEHLER" in report

    # State darf nicht aktualisiert worden sein
    with open(state_path) as f:
        new_state = json.load(f)
    assert new_state["last_check"] == "2026-07-07"
