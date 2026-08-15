from __future__ import annotations

import json
import time

import pytest

from multiai import modelresolve as mr


# --- pick_tag / resolve: die reine Logik ---------------------------------

def test_exact_match_is_left_alone():
    catalog = {"glm-5.2", "kimi-k3"}
    assert mr.resolve("glm-5.2", catalog) == "glm-5.2"


def test_bare_name_resolves_to_the_only_available_tag():
    """Der Fall, der den Analytiker-Sitz gekostet hat."""
    catalog = {"deepseek-v4-pro:preview", "qwen3.5:397b"}
    assert mr.resolve("deepseek-v4-pro", catalog) == "deepseek-v4-pro:preview"


def test_dated_tag_beats_preview():
    """Ein eingefrorener Stand ist reproduzierbar, preview ist ein bewegliches Ziel."""
    catalog = {"deepseek-v4-pro:preview", "deepseek-v4-pro:0813"}
    assert mr.resolve("deepseek-v4-pro", catalog) == "deepseek-v4-pro:0813"


def test_newest_dated_tag_wins():
    catalog = {"deepseek-v4-pro:0731", "deepseek-v4-pro:0813", "deepseek-v4-pro:preview"}
    assert mr.resolve("deepseek-v4-pro", catalog) == "deepseek-v4-pro:0813"


def test_stale_tag_resolves_to_the_current_one():
    """Konfiguriert ist ein Tag, der abgeraeumt wurde."""
    catalog = {"deepseek-v4-pro:preview"}
    assert mr.resolve("deepseek-v4-pro:0813", catalog) == "deepseek-v4-pro:preview"


def test_unknown_base_name_is_never_substituted():
    """Ein wirklich verschwundenes Modell darf nicht durch ein fremdes ersetzt werden.

    Lieber ein klarer Provider-Fehler auf dem Sitz als ein stiller Tausch des
    Labs — die Lab-Diversitaet ist der Zweck des Rats.
    """
    catalog = {"glm-5.2", "kimi-k3"}
    assert mr.resolve("llama4:900b", catalog) == "llama4:900b"


def test_sibling_models_are_not_confused():
    """`deepseek-v4-flash` ist nicht `deepseek-v4-pro`."""
    catalog = {"deepseek-v4-flash:0731", "deepseek-v4-pro:preview"}
    assert mr.resolve("deepseek-v4-pro", catalog) == "deepseek-v4-pro:preview"
    assert mr.resolve("deepseek-v4-flash", catalog) == "deepseek-v4-flash:0731"


def test_empty_catalog_changes_nothing():
    """Katalog nicht erreichbar -> Konfiguration bleibt unangetastet."""
    assert mr.resolve("deepseek-v4-pro", set()) == "deepseek-v4-pro"


def test_resolve_all_reports_only_real_changes():
    catalog = {"deepseek-v4-pro:preview", "glm-5.2"}
    models, changes = mr.resolve_all(["deepseek-v4-pro", "glm-5.2"], catalog)
    assert models == ["deepseek-v4-pro:preview", "glm-5.2"]
    assert changes == [("deepseek-v4-pro", "deepseek-v4-pro:preview")]


def test_pick_tag_returns_none_without_candidates():
    assert mr.pick_tag("nope", {"glm-5.2"}) is None


# --- Cache ---------------------------------------------------------------

def test_fresh_cache_is_used_without_fetching(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"fetched_at": time.time(), "models": ["glm-5.2"]}), encoding="utf-8")

    def explode():
        raise AssertionError("darf bei frischem Cache nicht fetchen")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", explode)
    assert mr.load_catalog(str(path)) == {"glm-5.2"}


def test_expired_cache_triggers_a_fetch(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    old = time.time() - mr.CACHE_TTL_S - 1
    path.write_text(json.dumps({"fetched_at": old, "models": ["alt"]}), encoding="utf-8")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"neu"})
    assert mr.load_catalog(str(path)) == {"neu"}

    # und wurde neu geschrieben
    assert set(json.loads(path.read_text(encoding="utf-8"))["models"]) == {"neu"}


def test_fetch_failure_falls_back_to_stale_cache(tmp_path, monkeypatch):
    """Veraltete Namen sind besser als gar keine."""
    path = tmp_path / "cache.json"
    old = time.time() - mr.CACHE_TTL_S - 1
    path.write_text(json.dumps({"fetched_at": old, "models": ["alt"]}), encoding="utf-8")

    def boom():
        raise OSError("kein Netz")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", boom)
    assert mr.load_catalog(str(path)) == {"alt"}


def test_fetch_failure_without_cache_yields_empty_set(tmp_path, monkeypatch):
    def boom():
        raise OSError("kein Netz")

    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", boom)
    assert mr.load_catalog(str(tmp_path / "fehlt.json")) == set()


def test_corrupt_cache_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    path.write_text("{kaputt", encoding="utf-8")
    monkeypatch.setattr("multiai.modelcheck.fetch_ollama_models", lambda: {"neu"})
    assert mr.load_catalog(str(path)) == {"neu"}
