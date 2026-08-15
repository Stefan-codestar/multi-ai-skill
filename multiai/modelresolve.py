"""Aufloesung konfigurierter Modellnamen gegen den aktuellen Ollama-Katalog.

Warum das noetig ist: Labs raeumen ihre Tags ab. `deepseek-v4-pro` war ein
blanker Name, wurde zu `deepseek-v4-pro:0813`, und zwei Tage spaeter gab es nur
noch `deepseek-v4-pro:preview`. Ein fest verdrahteter Tag ist bei diesem Tempo
keine Stabilitaet, sondern eine Wartungsschuld mit Verfallsdatum — der Sitz
faellt still aus, bis jemand den Katalog von Hand nachschaut.

Diese Aufloesung faengt genau das ab: Ist der konfigurierte Name nicht im
Katalog, aber ein Tag mit demselben Basisnamen, wird auf diesen Tag
ausgewichen. Der Rat tagt vollzaehlig weiter, und der woechentliche
modelcheck meldet die Aenderung trotzdem — die Aufloesung ersetzt den Check
nicht, sie ueberbrueckt nur die Zeit bis zur Korrektur.

Ausfallsicher: Ist der Katalog nicht erreichbar, bleibt alles wie
konfiguriert. Eine kaputte Netzverbindung darf den Rat nicht lahmlegen.
"""
from __future__ import annotations

import json
import os
import time

CACHE_PATH_DEFAULT = os.path.expanduser("~/.multiai/catalog_cache.json")

# Der Katalog aendert sich in Tagen, nicht in Minuten. Sechs Stunden halten die
# HTTP-Last bei ~4 Anfragen pro Tag und fangen einen Tag-Wechsel trotzdem am
# selben Tag ab.
CACHE_TTL_S = 6 * 3600

FETCH_TIMEOUT_S = 10


def base_name(model: str) -> str:
    """`deepseek-v4-pro:0813` -> `deepseek-v4-pro`."""
    return model.split(":", 1)[0]


def _tag(model: str) -> str:
    """`deepseek-v4-pro:0813` -> `0813`; ohne Tag -> `''`."""
    _, sep, tag = model.partition(":")
    return tag if sep else ""


def _rank(model: str) -> tuple[int, str]:
    """Sortierschluessel: hoeher ist besser.

    Reihenfolge der Praeferenz:
      2 — datierter Tag (`:0813`): eingefroren, reproduzierbar, neuester gewinnt
      1 — sonstiger benannter Tag (`:397b`, `:latest`)
      0 — `:preview`: bewegliches Ziel, nur wenn es nichts Besseres gibt
    """
    tag = _tag(model)
    if tag == "preview":
        return (0, tag)
    if tag.isdigit():
        return (2, tag)
    return (1, tag)


def pick_tag(configured: str, catalog: set[str]) -> str | None:
    """Bester Ersatz-Tag fuer ``configured``, oder None wenn es keinen gibt.

    Rein und ohne Netz — der Katalog wird hereingereicht, damit das testbar
    bleibt.
    """
    base = base_name(configured)
    candidates = [m for m in catalog if base_name(m) == base]
    if not candidates:
        return None
    return max(sorted(candidates), key=_rank)


def resolve(configured: str, catalog: set[str]) -> str:
    """Gibt einen Namen zurueck, der im Katalog existiert — oder den Originalnamen.

    Der Originalname kommt zurueck, wenn er bereits passt oder wenn der
    Basisname gar nicht mehr vorkommt (dann ist das Modell wirklich weg und der
    Sitz soll mit einem klaren Provider-Fehler ausfallen, nicht stillschweigend
    durch ein fremdes Modell ersetzt werden).
    """
    if not catalog or configured in catalog:
        return configured
    return pick_tag(configured, catalog) or configured


def resolve_all(models: list[str], catalog: set[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Loest eine Liste auf. Return: (aufgeloeste Liste, [(vorher, nachher), …])."""
    out: list[str] = []
    changes: list[tuple[str, str]] = []
    for model in models:
        resolved = resolve(model, catalog)
        out.append(resolved)
        if resolved != model:
            changes.append((model, resolved))
    return out, changes


def _load_cache(path: str, now: float) -> set[str] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if now - float(data.get("fetched_at", 0)) > CACHE_TTL_S:
        return None
    models = data.get("models")
    return set(models) if isinstance(models, list) else None


def _save_cache(path: str, models: set[str], now: float) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": now, "models": sorted(models)}, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass  # Cache ist Beschleunigung, kein Zustand — Fehler sind egal.


def load_catalog(cache_path: str = CACHE_PATH_DEFAULT, force: bool = False) -> set[str]:
    """Katalog aus dem Cache oder frisch vom Ollama-Endpunkt.

    Gibt bei jedem Fehler eine leere Menge zurueck — ``resolve`` behandelt das
    als "nichts bekannt" und laesst die Konfiguration unangetastet.
    """
    now = time.time()

    if not force:
        cached = _load_cache(cache_path, now)
        if cached is not None:
            return cached

    try:
        # Lokaler Import: modelcheck zieht profiles nach, und profiles darf
        # dieses Modul importieren — ein Top-Level-Import waere zirkulaer.
        from .modelcheck import fetch_ollama_models

        models = fetch_ollama_models()
    except Exception:
        # Auch einen abgelaufenen Cache noch nehmen: veraltete Namen sind
        # besser als gar keine.
        stale = _load_cache(cache_path, now=0.0)
        return stale if stale is not None else set()

    _save_cache(cache_path, models, now)
    return models
