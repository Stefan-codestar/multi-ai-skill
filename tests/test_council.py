from __future__ import annotations

from multiai.config import MultiAIConfig
from multiai.council import (
    render_brief,
    render_failures,
    render_header,
    render_roster,
    render_seats,
)
from multiai.fanout import Draft
from multiai.profiles import get_profile


def _cfg(profile="claude", **kw):
    kw.setdefault("enable_logging", False)
    return MultiAIConfig.from_profile(profile, **kw)


def _drafts(n_ok=7, profile="claude"):
    models = get_profile(profile).worker_models
    roles = [s.role for s in get_profile(profile).seats]
    out = []
    for i, (model, role) in enumerate(zip(models, roles), start=1):
        ok = i <= n_ok
        out.append(
            Draft(
                model=model,
                content=f"Beitrag von {role}" if ok else "",
                ok=ok,
                error=None if ok else "Timeout",
                latency_s=1.0,
                role=role,
                seat=i,
            )
        )
    return out


# ── Header / Roster ────────────────────────────────────────────────────────

def test_header_names_profile_and_aggregator():
    header = render_header(_cfg("vps"), n_ok=5)
    assert "Profil: vps" in header
    assert "geantwortet: 5/7" in header
    assert "glm-5.2 (http)" in header


def test_roster_lists_every_seat():
    roster = render_roster(_cfg("vps"))
    for i in range(1, 8):
        assert f"| {i} |" in roster
    assert "`minimax-m3`" in roster


def test_failures_empty_when_all_present():
    assert render_failures(_drafts()) == ""


def test_failures_name_seat_and_error():
    out = render_failures(_drafts(n_ok=6))
    assert "Querdenker (kimi-k2.6)" in out
    assert "Timeout" in out


# ── Brief (Claude Code aggregiert) ─────────────────────────────────────────

def test_brief_contains_question_rules_and_every_contribution():
    brief = render_brief("Was ist besser: A oder B?", _drafts(), _cfg())
    assert "SYNTHESE-AUFTRAG" in brief
    assert "Was ist besser: A oder B?" in brief
    assert "SYNTHESE-REGELN" in brief
    for role in ("Analytiker", "Ingenieur", "Skeptiker", "Stratege",
                 "Pragmatiker", "Erklaerer", "Querdenker"):
        assert f"Beitrag von {role}" in brief


def test_brief_tells_claude_the_material_is_not_the_answer():
    brief = render_brief("Frage?", _drafts(), _cfg())
    assert "KEINE" in brief and "Antwort an den Nutzer" in brief


def test_brief_counts_contributions():
    brief = render_brief("Frage?", _drafts(n_ok=5), _cfg())
    assert "BEITRAEGE DES RATS (5/7)" in brief
    assert "Nicht erschienene Sitze" in brief


def test_brief_without_any_contribution_points_at_solo_mode():
    brief = render_brief("Frage?", _drafts(n_ok=0), _cfg())
    assert "KEIN BEITRAG ERHALTEN" in brief
    assert "--strategy seats" in brief
    assert "Frage?" in brief


# ── Seats (Solo-Rat) ───────────────────────────────────────────────────────

def test_seats_lists_all_seven_lenses():
    out = render_seats("Frage?", _cfg())
    assert out.count("### Sitz ") == 7
    assert "DER SKEPTIKER" in out
    assert "DER QUERDENKER" in out


def test_seats_warns_that_it_is_one_model():
    out = render_seats("Frage?", _cfg())
    assert "SOLO-MODUS" in out
    assert "sieben Blickwinkel" in out


def test_seats_names_the_model_each_seat_would_use():
    out = render_seats("Frage?", _cfg("vps"))
    assert "minimax-m3" in out
    assert "deepseek-v4-pro" in out


def test_seats_without_lenses_marks_neutral():
    out = render_seats("Frage?", _cfg(use_lenses=False))
    assert "keine Rolle gesetzt" in out
