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
