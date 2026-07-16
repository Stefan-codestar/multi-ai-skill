from __future__ import annotations

import json
import os


def log_run(record: dict, log_dir: str) -> None:
    try:
        os.makedirs(log_dir, exist_ok=True)
        runs_dir = os.path.join(log_dir, "runs")
        os.makedirs(runs_dir, exist_ok=True)

        ts = record.get("ts")
        ts_str = str(ts) if ts is not None else "0"
        full_path = os.path.join(runs_dir, f"{ts_str}.json")

        compact = {
            "ts": record.get("ts"),
            "iso": record.get("iso"),
            "question": record.get("question", "")[:200],
            "strategy": record.get("strategy"),
            "aggregator": record.get("aggregator"),
            "total_s": record.get("total_s"),
            "n_ok": record.get("n_ok"),
            "drafts": [
                {
                    "model": d.get("model"),
                    "ok": d.get("ok"),
                    "latency_s": d.get("latency_s"),
                    "words": d.get("words"),
                }
                for d in record.get("drafts", [])
            ],
            "final_words": record.get("final_words"),
        }

        with open(os.path.join(log_dir, "runs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(compact, ensure_ascii=False) + "\n")

        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
    except Exception:
        pass
