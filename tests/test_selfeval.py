from __future__ import annotations

import os

from multiai.selfeval import (
    CORE_FILES,
    EVAL_AXES,
    MAX_CHARS_PER_FILE,
    _repo_root,
    build_self_eval_question,
)


def test_repo_root_contains_skill_md():
    assert os.path.isfile(os.path.join(_repo_root(), "SKILL.md"))


def test_question_contains_every_eval_axis():
    q = build_self_eval_question()
    for axis in EVAL_AXES:
        head = axis.split("—")[0].strip()
        assert head in q


def test_question_embeds_the_core_files():
    q = build_self_eval_question()
    for rel in CORE_FILES:
        assert f"### `{rel}`" in q


def test_question_describes_both_profiles_and_seats():
    q = build_self_eval_question()
    assert "Profil `claude`" in q
    assert "Profil `vps`" in q
    assert "claude-opus-5" in q
    assert "glm-5.2" in q
    assert "Querdenker" in q


def test_question_asks_for_concrete_suggestions():
    q = build_self_eval_question()
    assert "Verbesserungsvorschlaege" in q
    assert "Datei, Stelle und Aenderung" in q


def test_missing_file_is_skipped_not_fatal(tmp_path):
    q = build_self_eval_question(repo_root=str(tmp_path), files=["gibt-es-nicht.md"])
    assert "gibt-es-nicht" not in q
    assert "Rat der Sieben" in q


def test_long_files_are_capped(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("x" * (MAX_CHARS_PER_FILE * 3), encoding="utf-8")
    q = build_self_eval_question(repo_root=str(tmp_path), files=["big.py"])
    assert "gekuerzt" in q
    assert len(q) < MAX_CHARS_PER_FILE * 3
