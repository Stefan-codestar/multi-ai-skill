from __future__ import annotations

import pytest

from multiai.profiles import (
    COUNCIL_SIZE,
    MODEL_ORIGINS,
    PROFILES,
    all_http_models,
    all_worker_models,
    diversity_report,
    get_profile,
    with_models,
)


def test_get_profile_default_and_unknown():
    assert get_profile(None).name == "claude"
    assert get_profile("VPS").name == "vps"
    with pytest.raises(ValueError, match="Unbekanntes Profil"):
        get_profile("hermes-2")


def test_every_profile_has_seven_distinct_seats():
    for profile in PROFILES.values():
        assert len(profile.seats) == COUNCIL_SIZE
        assert len({s.model for s in profile.seats}) == COUNCIL_SIZE
        assert len({s.role for s in profile.seats}) == COUNCIL_SIZE


def test_every_seat_comes_from_a_distinct_lab():
    """Diversitaet ist der Zweck des Rats — zwei Sitze aus demselben Lab waeren Groupthink."""
    for profile in PROFILES.values():
        labs = [s.lab for s in profile.seats]
        assert len(set(labs)) == COUNCIL_SIZE, f"{profile.name}: {labs}"


def test_council_spans_multiple_countries():
    for profile in PROFILES.values():
        assert len({s.country for s in profile.seats}) >= 3


def test_all_models_have_known_origin():
    for profile in PROFILES.values():
        for seat in profile.seats:
            assert seat.model in MODEL_ORIGINS
            assert seat.lab != "unbekannt"
        assert profile.aggregator_model in MODEL_ORIGINS


def test_profiles_differ_in_aggregator():
    claude, vps = get_profile("claude"), get_profile("vps")
    assert claude.aggregator_model != vps.aggregator_model
    assert claude.aggregator_kind == "inprocess"
    assert vps.aggregator_kind == "http"


def test_glm_sits_on_claude_council_but_aggregates_on_vps():
    """glm-5.2 ist auf dem VPS Aggregator und darf dort nicht mitreden."""
    assert "glm-5.2" in get_profile("claude").worker_models
    assert "glm-5.2" not in get_profile("vps").worker_models


def test_with_models_preserves_roles():
    profile = with_models(get_profile("vps"), ["x", "y", "z"])
    assert profile.worker_models == ["x", "y", "z"]
    assert [s.role for s in profile.seats] == ["Analytiker", "Ingenieur", "Skeptiker"]


def test_with_models_rotates_roles_when_more_models_than_seats():
    profile = with_models(get_profile("vps"), [f"m{i}" for i in range(9)])
    assert len(profile.seats) == 9
    assert profile.seats[7].role == "Analytiker"   # Rolle 1 wiederholt sich


def test_with_models_empty_is_noop():
    profile = get_profile("vps")
    assert with_models(profile, []) is profile


def test_all_worker_models_covers_both_profiles():
    models = all_worker_models()
    assert "minimax-m3" in models       # nur im VPS-Profil
    assert "glm-5.2" in models        # nur im Claude-Profil als Sitz
    assert models == sorted(set(models))


def test_all_http_models_includes_http_aggregator_not_inprocess():
    models = all_http_models()
    assert "glm-5.2" in models
    assert "claude-opus-5" not in models


def test_diversity_report_mentions_aggregator():
    report = diversity_report(get_profile("vps"))
    assert "7 Sitze" in report
    assert "glm-5.2" in report


def test_seat_by_role_is_case_insensitive():
    seat = get_profile("vps").seat_by_role("skeptiker")
    assert seat is not None and seat.model == "nemotron-3-ultra"
    assert get_profile("vps").seat_by_role("Hofnarr") is None
