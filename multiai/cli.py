from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import MultiAIConfig
from .council import render_header, render_roster
from .pipeline import run_multiai, run_multiai_stream
from .profiles import DEFAULT_PROFILE_NAME, PROFILES, diversity_report, get_profile
from .selfeval import build_self_eval_question


def _draft_to_dict(d: Any) -> dict[str, Any]:
    return {
        "seat": d.seat,
        "role": d.role,
        "model": d.model,
        "content": d.content,
        "ok": d.ok,
        "error": d.error,
        "latency_s": d.latency_s,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="multiai",
        description="Rat der Sieben — eine Frage an sieben Modelle, eine Antwort zurueck.",
    )
    parser.add_argument("question", nargs="?", help="Die Frage an den Rat.")
    parser.add_argument(
        "--profile", choices=sorted(PROFILES),
        help="Umgebungsprofil (Standard: claude).",
    )
    parser.add_argument("--show-drafts", action="store_true",
                        help="Einzelbeitraege der Sitze mit ausgeben.")
    parser.add_argument("--models", help="Kommaseparierte Modelle fuer die Sitze.")
    parser.add_argument("--lead", help="Aggregator-Modell ueberschreiben.")
    parser.add_argument("--strategy", choices=["moa", "concat", "brief", "seats"],
                        help="moa=Modell synthetisiert, brief=Claude Code "
                             "synthetisiert, seats=Solo-Rat ohne Netz, concat=roh.")
    parser.add_argument("--base-url", help="Override Base-URL.")
    parser.add_argument("--max-parallel", type=int,
                        help="Gleichzeitige Sitze (Ollama Cloud Pro: 3).")
    parser.add_argument("--quorum", type=int, help="Noetige Beitraege fuer volles Quorum.")
    parser.add_argument("--timeout", type=int, help="Timeout je Sitz in Sekunden.")
    parser.add_argument("--no-lenses", action="store_true",
                        help="Ohne Rollen-Prompts — alle Sitze antworten neutral.")
    parser.add_argument("--no-log", action="store_true", help="Run-Logging deaktivieren.")
    parser.add_argument("--log-dir", help="Verzeichnis fuer Run-Logs.")
    parser.add_argument("--json", action="store_true", help="Result als JSON ausgeben.")
    parser.add_argument("--stream", action="store_true",
                        help="Synthese live streamen (nur Profile mit HTTP-Aggregator).")
    parser.add_argument("--self-eval", action="store_true",
                        help="Der Rat bewertet diesen Skill selbst.")
    parser.add_argument("--roster", action="store_true",
                        help="Sitzbesetzung anzeigen und beenden.")
    return parser


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.profile:
        overrides["profile"] = args.profile
    if args.models:
        overrides["worker_models"] = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.lead:
        overrides["aggregator_model"] = args.lead
        overrides["aggregator_kind"] = "http"
    if args.strategy:
        overrides["strategy"] = args.strategy
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.max_parallel:
        overrides["max_parallel"] = args.max_parallel
    if args.quorum:
        overrides["quorum_k"] = args.quorum
    if args.timeout:
        overrides["timeout_s"] = args.timeout
    if args.no_lenses:
        overrides["use_lenses"] = False
    if args.no_log:
        overrides["enable_logging"] = False
    if args.log_dir:
        overrides["log_dir"] = args.log_dir
    return overrides


def _build_config(args: argparse.Namespace) -> MultiAIConfig:
    """Profil laden, dann CLI-Overrides anwenden.

    ``--models`` muss vor der Validierung greifen, weil es die Sitzzahl aendert;
    deshalb geht der Weg ueber ``from_profile`` statt ueber Attributzuweisung.
    """
    overrides = _overrides_from_args(args)
    profile_name = overrides.pop("profile", None)
    if profile_name or "worker_models" in overrides:
        return MultiAIConfig.from_profile(
            get_profile(profile_name), **overrides
        )
    return MultiAIConfig.from_dict(overrides)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.roster:
        for name in sorted(PROFILES):
            profile = PROFILES[name]
            marker = " (Standard)" if name == DEFAULT_PROFILE_NAME else ""
            print(f"\n== Profil: {name}{marker} ==")
            print(profile.description)
            print(diversity_report(profile))
            print()
            print(render_roster(MultiAIConfig.from_profile(profile), profile))
        return 0

    if args.self_eval:
        if args.question:
            print("Fehler: --self-eval nimmt keine Frage entgegen.", file=sys.stderr)
            return 2
        question = build_self_eval_question()
    elif args.question:
        question = args.question
    else:
        print("Fehler: Frage fehlt (oder --self-eval / --roster nutzen).",
              file=sys.stderr)
        return 2

    try:
        config = _build_config(args)
    except (ValueError, TypeError) as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2

    # Hinweis geht auf stderr und stoert deshalb auch --json nicht.
    if args.stream and config.aggregator_kind == "inprocess":
        print(
            f"Hinweis: Profil '{config.profile}' aggregiert in-process "
            f"({config.aggregator_model}) — --stream hat hier keine Wirkung.",
            file=sys.stderr,
        )

    try:
        if args.stream and not args.json:
            for chunk in run_multiai_stream(question, config=config):
                print(chunk, end="", flush=True)
            print()
            return 0
        result = run_multiai(question, config=config)
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(
            {
                "profile": result.profile,
                "final": result.final,
                "aggregator_model": result.aggregator_model,
                "strategy": result.strategy,
                "needs_external_synthesis": result.needs_external_synthesis,
                "used_quorum": result.used_quorum,
                "n_ok": result.n_ok,
                "council_size": result.council_size,
                "drafts": [_draft_to_dict(d) for d in result.drafts],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    print(result.final)
    if args.show_drafts and result.drafts:
        print("\n--- Beitraege der Sitze ---")
        print(render_header(config, n_ok=result.n_ok))
        for d in result.drafts:
            status = "ok" if d.ok else f"AUSGEFALLEN: {d.error}"
            print(f"\n[Sitz {d.seat}: {d.label}] ({d.latency_s:.1f}s) {status}")
            if d.content:
                print(d.content)
    return 0
