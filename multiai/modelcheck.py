from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

from .config import DEFAULT_WORKER_MODELS
from .providers import _load_key


STATE_PATH_DEFAULT = os.path.expanduser("~/.multiai/fallback_check.json")


def is_due(last_iso_date: str | None, today: datetime.date) -> bool:
    """True wenn kein letzter Check bekannt ist oder die ISO-Kalenderwoche abweicht."""
    if last_iso_date is None:
        return True
    try:
        last = datetime.date.fromisoformat(last_iso_date)
    except ValueError:
        return True
    return last.isocalendar()[:2] != today.isocalendar()[:2]


def fetch_ollama_models() -> set[str]:
    """Laedt den Ollama-Cloud-Katalog. Wirft bei Fehler."""
    api_key = _load_key("OLLAMA_API_KEY")
    url = "https://ollama.com/v1/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return {m["id"] for m in body.get("data", [])}


def fetch_openrouter_models() -> set[str]:
    """Laedt den OpenRouter-Katalog (oeffentlich, Key optional)."""
    url = "https://openrouter.ai/api/v1/models"
    headers: dict[str, str] = {}
    try:
        api_key = _load_key("OPENROUTER_API_KEY")
        headers["Authorization"] = f"Bearer {api_key}"
    except Exception:
        pass
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return {m["id"] for m in body.get("data", [])}


def _load_state(path: str) -> dict | None:
    """Laedt State-JSON. Fehlende/kaputte Datei -> None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_state(path: str, state: dict) -> None:
    """Schreibt State-JSON atomar. Legt Verzeichnis an falls noetig."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def _compute_fallback_gaps() -> list[str]:
    """Gibt immer eine leere Liste zurueck — kein Fallback-Tier konfiguriert (Ollama Cloud only)."""
    return []


def run_check(
    state_path: str = STATE_PATH_DEFAULT,
    force: bool = False,
    today: datetime.date | None = None,
) -> tuple[bool, str]:
    """Fuehrt den woechentlichen Fallback-Check aus.

    Return: (ran, report). ran=True wenn der Check ausgefuehrt wurde.
    Erste Report-Zeile: 'BASELINE ERSTELLT' (erster Lauf ohne Warnungen),
    'AENDERUNGEN GEFUNDEN' oder 'KEINE AENDERUNGEN'.
    """
    if today is None:
        today = datetime.date.today()

    state = _load_state(state_path)
    is_first_run = not state
    last_check = state.get("last_check") if state else None

    if not force and not is_due(last_check, today):
        return (False, f"Fallback-Check nicht faellig (zuletzt: {last_check}).")

    # --- Fetches ---
    ollama_models: set[str] | None = None
    fetch_errors: list[str] = []

    try:
        ollama_models = fetch_ollama_models()
    except Exception as e:
        fetch_errors.append(f"Ollama-Katalog: {e}")

    if fetch_errors:
        lines = ["AENDERUNGEN GEFUNDEN"]
        for err in fetch_errors:
            lines.append(f"FEHLER: {err}")
        lines.append("State NICHT aktualisiert (Fetch-Fehler).")
        return (True, "\n".join(lines))

    assert ollama_models is not None

    report_lines: list[str] = []
    has_changes = False

    # a) Ollama-Katalog-Diff
    prev_ollama = set(state.get("ollama_models", [])) if state else None
    if prev_ollama is None:
        report_lines.append(
            f"Erster Lauf — Baseline gespeichert ({len(ollama_models)} Modelle)."
        )
    else:
        added = ollama_models - prev_ollama
        removed = prev_ollama - ollama_models
        for m in sorted(added):
            has_changes = True
            report_lines.append(f"+ {m}")
        for m in sorted(removed):
            has_changes = True
            report_lines.append(f"- {m}")

    # b) Worker-Verfuegbarkeit im Ollama-Katalog
    for worker in DEFAULT_WORKER_MODELS:
        if worker not in ollama_models:
            has_changes = True
            report_lines.append(f"WARNUNG: Worker '{worker}' nicht im Ollama-Katalog.")

    # e) Fallback-Luecken — statisch; Change-Markierung nur bei Aenderung
    gaps_now = _compute_fallback_gaps()
    prev_gaps = state.get("fallback_gaps") if state else None

    if prev_gaps is not None:
        new_gaps = [g for g in gaps_now if g not in prev_gaps]
        gone_gaps = [g for g in prev_gaps if g not in gaps_now]
        for g in new_gaps:
            has_changes = True
            report_lines.append(f"LUECKE (neu): Worker '{g}' hat kein Fallback-Tier.")
        for g in gone_gaps:
            has_changes = True
            report_lines.append(f"LUECKE geloest: Worker '{g}' hat jetzt Fallback-Tier.")
        for g in gaps_now:
            if g not in new_gaps:
                report_lines.append(f"LUECKE: Worker '{g}' hat kein Fallback-Tier.")
    else:
        for g in gaps_now:
            report_lines.append(f"LUECKE: Worker '{g}' hat kein Fallback-Tier.")

    # Erste Zeile
    if is_first_run and not has_changes:
        first_line = "BASELINE ERSTELLT"
    else:
        first_line = "AENDERUNGEN GEFUNDEN" if has_changes else "KEINE AENDERUNGEN"
    report = first_line + "\n" + "\n".join(report_lines)

    # State speichern bei Erfolg
    new_state = {
        "last_check": today.isoformat(),
        "ollama_models": sorted(ollama_models),
        "fallback_gaps": gaps_now,
    }
    _save_state(state_path, new_state)

    return (True, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Woechentlicher Fallback-Modell-Check"
    )
    parser.add_argument(
        "--force", action="store_true", help="Check auch ausfuehren wenn nicht faellig."
    )
    parser.add_argument(
        "--state-path", default=STATE_PATH_DEFAULT, help="Pfad zur State-Datei."
    )
    args = parser.parse_args()

    _ran, report = run_check(state_path=args.state_path, force=args.force)
    print(report)
    sys.exit(0)
