from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import MultiAIConfig
from .pipeline import run_multiai, run_multiai_stream


def _draft_to_dict(d: Any) -> dict[str, Any]:
    return {
        "model": d.model,
        "content": d.content,
        "ok": d.ok,
        "error": d.error,
        "latency_s": d.latency_s,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MultiAI: Frage parallel an mehrere LLMs stellen.")
    parser.add_argument("question", help="Die Frage an die Modelle.")
    parser.add_argument("--show-drafts", action="store_true", help="Einzelantworten mit ausgeben.")
    parser.add_argument("--models", help="Kommaseparierte Worker-Modelle.")
    parser.add_argument("--lead", help="Aggregator-Modell.")
    parser.add_argument("--strategy", choices=["moa", "concat"], help="Synthese-Strategie.")
    parser.add_argument("--base-url", help="Override Base-URL.")
    parser.add_argument("--no-log", action="store_true", help="Run-Logging deaktivieren.")
    parser.add_argument("--log-dir", help="Verzeichnis fuer Run-Logs.")
    parser.add_argument("--json", action="store_true", help="Result als JSON ausgeben.")
    parser.add_argument("--stream", action="store_true", help="Synthesizer-Antwort live streamen.")

    args = parser.parse_args(argv)

    overrides: dict[str, Any] = {}
    if args.models:
        overrides["worker_models"] = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.lead:
        overrides["aggregator_model"] = args.lead
    if args.strategy:
        overrides["strategy"] = args.strategy
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.no_log:
        overrides["enable_logging"] = False
    if args.log_dir:
        overrides["log_dir"] = args.log_dir

    config = MultiAIConfig.from_dict(overrides)

    try:
        if args.stream and not args.json:
            # Streaming-Modus: Synthesizer-Antwort chunkweise ausgeben
            for chunk in run_multiai_stream(args.question, config=config):
                print(chunk, end="", flush=True)
            print()  # final newline
            return 0
        result = run_multiai(args.question, config=config)
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    if args.json:
        out = {
            "final": result.final,
            "aggregator_model": result.aggregator_model,
            "strategy": result.strategy,
            "used_quorum": result.used_quorum,
            "n_ok": result.n_ok,
            "drafts": [_draft_to_dict(d) for d in result.drafts],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(result.final)
        if args.show_drafts:
            print("\n--- Drafts ---")
            for d in result.drafts:
                status = "ok" if d.ok else f"FAILED: {d.error}"
                print(f"\n[{d.model}] ({d.latency_s:.3f}s) {status}")
                if d.content:
                    print(d.content)

    return 0
