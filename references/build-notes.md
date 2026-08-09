# multiai — Build-Notizen (Session 2026-07-16)

## Ausgangslage
Vorlage: `E:\Dateien\Hermes Projects\multiai-skill-vorlage` (Romans Setup, 8 Worker, ClinePass + Ollama Cloud Max)
Ziel: Angepasste Version für Ollama Cloud Pro (3 Worker, kein ClinePass)

---

## Provider-Vereinfachung: ClinePass entfernen

Die Vorlage hat ein 3-Tier-Routing: `ClinePass → Ollama Cloud → OpenRouter`.
Für Ollama Cloud Pro (kein ClinePass) wurde `RoutingProvider` auf 10 Zeilen reduziert:

```python
class RoutingProvider:
    def __init__(self, ollama=None, ollama_base_url=DEFAULT_BASE_URL, **_ignored):
        self._ollama = ollama or OllamaCloudProvider(base_url=ollama_base_url)

    def complete(self, model, messages, **kwargs):
        return self._ollama.complete(model, messages, **kwargs)
```

`**_ignored` ist wichtig: `pipeline.py` übergibt `ollama_base_url=` als kwarg — ohne `**_ignored` würde `RoutingProvider(openrouter=None, cline=None)` einen TypeError werfen.

---

## Testanpassungen

### test_config.py
Modellnamen und Token-Limits (32768 → 16384) anpassen:
```python
assert c.worker_models == ["deepseek-v4-pro", "qwen3.5:397b", "glm-5.2"]
assert c.worker_max_tokens == 16384
assert c.aggregator_max_tokens == 16384
```

### test_providers.py
3 ClinePass-Tests ersetzen durch:
- `test_routing_provider_delegates_to_ollama` — normaler Erfolgsfall
- `test_routing_provider_raises_on_ollama_error` — kein Fallback vorhanden
- `test_routing_provider_ignores_extra_kwargs` — `openrouter=None, cline=None` darf keinen Fehler werfen

### test_pipeline.py
8 Modellnamen → 3 Modellnamen. `assert result.n_ok == 8` → `assert result.n_ok == 3`. `assert len(worker_calls) == 8` → `== 3`.

### test_modelcheck.py
Komplett neu geschrieben (ClinePass/OpenRouter-Logik raus). State-Format:
```json
{"last_check": "...", "ollama_models": [...], "fallback_gaps": []}
```
Kein `openrouter_mapped_ok` mehr im State.

---

## Windows-spezifisch

- `python3` → zeigt auf Hermes-interne venv (kein pytest). Immer `python` oder `C:/Python313/python.exe`.
- pytest installieren: `C:/Python313/python.exe -m pip install pytest`
- Tests ausführen: `cd "E:/Dateien/Hermes Projects/skill-multiai" && C:/Python313/python.exe -m pytest tests/ -v`
- Git braucht bei erstem Commit: `git config user.email` + `git config user.name`

---

## Ollama Cloud Pro vs Max

| | Pro ($20/mo) | Max ($100/mo) |
|--|--|--|
| Gleichzeitige Modelle | 3 | 10 |
| Sinnvolle Worker-Zahl | 3 | 8 |
| Session-Limits | Ja (alle 5h reset) | Ja (größer) |

Pro mit 8 Workern: Worker 4-8 warten → kein Parallelitätsvorteil, dafür Kontingentverbrauch.

---

## API-Key Sicherheit

Der Key wird gelesen aus (in dieser Reihenfolge):
1. `os.environ["OLLAMA_API_KEY"]`
2. `~/.env` (= `C:\Users\AKINO\.env`)
3. `~/.hermes/.env`

Key-Rotation: ollama.com → Account → API Keys. Nach Rotation neuen Key in `~/.env` eintragen.
**Key niemals im Chat teilen** — er landet in der Session-DB und ist dauerhaft sichtbar.

---

## Finale Testbilanz

| Phase | Tests |
|-------|-------|
| Sprint 1 (Vorlage 1:1) | 47/47 PASS |
| Sprint 2 (nach Anpassung) | 42/42 PASS |

5 Tests weniger: ClinePass-spezifische Tests (3 in test_providers, mehre in test_modelcheck) wurden durch neue, zum vereinfachten Setup passende Tests ersetzt.

---

# Ausbau zum Rat der Sieben (Session 2026-08-09)

## Ziel
Aus dem 3-Worker-`multiai` einen 7-Sitze-Rat machen, der unter Claude Code
UND auf dem Hermes VPS laeuft — mit unterschiedlichen Aggregatoren.

## Struktur-Aenderungen

| Datei | Was |
|-------|-----|
| `profiles.py` (neu) | Sitze, Rollen-Prompts, die zwei Profile, Diversitaets-Report |
| `council.py` (neu) | Brief- und Solo-Modus-Rendering (Ausgabe an Claude Code) |
| `selfeval.py` (neu) | baut die Selbstbewertungs-Frage aus dem Repo |
| `config.py` | profilbasiert, `validate()`, `from_profile()`, `max_parallel` |
| `fanout.py` | Lens je Sitz, `Draft.role`/`.seat`/`.label`, Parallelitaetsgrenze |
| `pipeline.py` | Strategien `brief` und `seats`, Profil im Run-Log |
| `cli.py` | `--profile`, `--roster`, `--self-eval`, `--max-parallel`, `--no-lenses` |
| `modelcheck.py` | `WATCHED_MODELS` statt `DEFAULT_WORKER_MODELS` |

## Fallstricke aus dieser Session

### 1. Rollennamen im Aggregator-Prompt kollidieren mit Test-Assertions
`AGGREGATOR_SYSTEM_PROMPT` zaehlt alle sieben Rollen auf. Ein Test wie
`assert "Ingenieur" not in system` (fuer "ausgefallener Sitz fehlt") schlaegt
deshalb fehl, obwohl der Code stimmt. Auf das Label pruefen, nicht auf den
Rollennamen: `assert "### 2. Ingenieur (b)" not in system`.

### 2. `--stream`-Hinweis gehoert nach stderr, nicht hinter `not --json`
Erst war der Hinweis "in-process, --stream wirkungslos" an `not args.json`
gekoppelt und blieb bei `--json` stumm. stderr stoert die JSON-Ausgabe auf
stdout nicht — der Hinweis kommt jetzt immer.

### 3. `--models` muss vor der Validierung greifen
`--models a,b,c` aendert die Sitzzahl. Wird es per `setattr` nachtraeglich
gesetzt, passen `seat_roles`/`seat_lenses` nicht mehr zu `worker_models` und
`validate()` schlaegt zu Recht Alarm. Deshalb geht `cli._build_config` bei
`--models` und `--profile` ueber `from_profile()` statt ueber `from_dict()`.

### 4. Parallelitaetsgrenze ist kein Detail
Ohne `max_parallel=3` gehen auf Ollama Cloud Pro alle sieben Anfragen raus,
vier warten server-seitig und laufen dabei in den 240-s-Client-Timeout. Sieht
aus wie sieben kaputte Modelle, ist aber nur eine fehlende Semaphore.
`test_max_parallel_limits_concurrency` haelt es mit einer `threading.Barrier`
fest.

## Umgebungsgrenze dieser Session

Gebaut in einer Claude-Code-Web-Sandbox ohne `OLLAMA_API_KEY`; `ollama.com` und
`openrouter.ai` sind dort per Egress-Policy gesperrt (403 auf CONNECT). Kein
Live-Lauf der sieben Sitze moeglich. Abgenommen wurde deshalb offline
(Testsuite) plus `--self-eval --strategy seats`. Der Lauf mit echten sieben
Modellen gehoert auf eine Maschine mit Key.

## Testbilanz

| Phase | Tests |
|-------|-------|
| Sprint 2 (3 Worker) | 42 |
| Rat der Sieben | 118 |

Neu: `test_profiles.py` (14), `test_council.py` (12), `test_selfeval.py` (7),
`test_cli.py` (13); `test_pipeline.py` von 6 auf 22 erweitert.
