from __future__ import annotations

import json
import os

from multiai.logio import log_run


def _record():
    return {
        "ts": 1700000000.0,
        "iso": "2026-06-21T12:00:00",
        "question": "Q" * 500,
        "strategy": "moa",
        "aggregator": "glm-5.2",
        "total_s": 12.3,
        "n_ok": 2,
        "drafts": [
            {"model": "glm-5.2", "ok": True, "latency_s": 1.0, "error": None, "content": "AAA BBB", "words": 2},
            {"model": "kimi-k2.7-code", "ok": False, "latency_s": 0.5, "error": "boom", "content": "", "words": 0},
        ],
        "final": "Finale Antwort hier",
        "final_words": 3,
    }


def test_log_run_writes_index_and_full(tmp_path):
    log_dir = str(tmp_path / "logs")
    log_run(_record(), log_dir)
    index = os.path.join(log_dir, "runs.jsonl")
    assert os.path.isfile(index)
    line = open(index, encoding="utf-8").readline()
    obj = json.loads(line)
    # kompakter Index: Metriken, gekuerzte Frage, KEINE vollen draft-Texte
    assert obj["strategy"] == "moa"
    assert obj["n_ok"] == 2
    assert len(obj["question"]) <= 200
    assert "content" not in obj["drafts"][0]
    assert obj["drafts"][0]["words"] == 2
    # volle Aufzeichnung existiert und enthaelt content + final
    runs_dir = os.path.join(log_dir, "runs")
    files = os.listdir(runs_dir)
    assert len(files) == 1
    full = json.load(open(os.path.join(runs_dir, files[0]), encoding="utf-8"))
    assert full["drafts"][0]["content"] == "AAA BBB"
    assert full["final"] == "Finale Antwort hier"


def test_log_run_is_silent_on_bad_dir(tmp_path):
    # Datei statt Verzeichnis -> makedirs scheitert; log_run darf NICHT werfen
    bad = tmp_path / "afile"
    bad.write_text("x")
    log_run(_record(), str(bad / "sub"))  # darf keine Exception werfen
