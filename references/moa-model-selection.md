# MoA-Modell-Auswahl — Erkenntnisse aus Session 2026-07-16

## Prompt-Formulierung: "Aggregator" ist mehrdeutig

Wenn eine Frage an die MoA-Engine das Wort "Aggregator" ohne MoA-Kontext enthält,
interpretieren die Worker-Modelle dies als **API-Gateway/Routing-Plattform**
(z.B. OpenRouter, Poe.com, ChatHub) — nicht als MoA-Synthetisierer.

### Beispiel (schlecht):
> "Wer wäre der beste Aggregator und warum?"

→ Alle 3 Worker empfahlen OpenRouter als "besten Aggregator".

### Beispiel (gut):
> "Welches LLM eignet sich am besten als Synthetisierer/Aggregator in einem
> Mixture-of-Agents-Setup, und welche 3 Worker-Modelle würdet ihr kombinieren?"

→ Worker empfahlen konkrete LLMs für die Aggregator-Rolle.

### Faustregel
Immer "Synthetisierer/Aggregator in einem Mixture-of-Agents-Setup" schreiben,
niemals nur "Aggregator" allein.

---

## Self-Bias bei Modell-Empfehlungen

Wenn Worker-Modelle gefragt werden, welches Modell als Aggregator geeignet ist,
empfehlen sie **sich selbst**. Beobachtet am 2026-07-16:

| Worker | Empfohlener Aggregator | Self-Bias? |
|--------|----------------------|-----------|
| `deepseek-v4-pro` | deepseek-v4-pro | ✅ Ja |
| `qwen3.5:397b` | qwen2.5:72b (sich selbst, leicht umbenannt) | ✅ Ja |
| `glm-5.2` | llama3.1:405b | ❌ Nein — neutral |

**Erkenntnis:** `glm-5.2` (der aktuelle Aggregator) zeigte den geringsten Self-Bias
und war am neutralsten. Das könnte ein Argument sein, glm-5.2 als Aggregator
beizubehalten — oder für einen Wechsel zu `llama3.1:405b`, falls verfügbar.

### Empfohlene Worker-Modelle (synthetisierte Antwort)
Für Ollama Cloud Pro:
1. `qwen2.5:72b` — Logik, Mathe, Code, multilingual (Dense)
2. `deepseek-v2.5` — Deep Reasoning, unkonventionelle Ansätze (MoE)
3. `mixtral:8x22b` — Kreativität, sprachliche Nuancen, europäische Perspektive (MoE)

Aggregator-Alternative: `llama3.1:405b` (128K Kontext, starkes Instruction Following)

### Diversitäts-Prinzip
- Verschiedene Architekturen (Dense vs. MoE) reduzieren Groupthink
- Verschiedene Entwicklungsteams (Meta, Alibaba, DeepSeek, Mistral) reduzieren
  systematische Fehler
- Der Synthesizer sollte **stärker** sein als die Worker, um deren Outputs
  kompetent bewerten zu können

---

## Ollama Cloud Pro Constraint

Der User hat **nur** Ollama Cloud Pro ($20/Monat) — keine externen Anbieter.
Bei Fragen, die Modellempfehlungen einholen, muss der Prompt explizit
einschränken:

> "Beschränke deine Empfehlung auf Modelle, die auf Ollama Cloud Pro verfügbar
> sind. Keine Modelle von OpenAI, Anthropic, Google oder anderen externen
> Anbietern."

Ohne diesen Constraint empfehlen die Modelle proprietäre Modelle (Claude 3.5
Sonnet, GPT-4o, Gemini 1.5 Flash), die der User nicht nutzen kann.

### Verfügbare Modellfamilien auf Ollama Cloud Pro (Stand 2026-07)
- DeepSeek (v2.5, v3, v4-pro)
- Qwen (2.5, 3.5)
- GLM (4, 5.2)
- Llama (3.1)
- Mistral / Mixtral
- Weitere Open-Weight-Modelle im Ollama-Katalog

### Nicht verfügbar (nicht empfehlen)
- OpenAI (GPT-4o, GPT-4, etc.)
- Anthropic (Claude 3.5 Sonnet, etc.)
- Google (Gemini 1.5 Flash/Pro, etc.)
- OpenRouter als "Aggregator" (ist ein API-Gateway, kein MoA-Synthetisierer)

---

## Wöchentlicher Fallback-Check Hinweis

Der Fallback-Check (`python -m multiai.modelcheck`) prüft, ob die konfigurierten
Worker-Modelle noch im Ollama-Cloud-Katalog verfügbar sind. Wenn ein Modell
verschwindet (z.B. weil Ollama es aus dem Katalog nimmt), warnt der Check mit
`WARNUNG: Worker '<modell>' nicht im Ollama-Katalog.`

Dies ist der primäre Mechanismus, um Modell-Verfügbarkeitsänderungen zu
entdecken — nicht die MoA-Engine selbst.

---

## Config-Änderung: Worker 3 glm-5.2 → mistral-large-3:675b (2026-07-16)

### Problem
`glm-5.2` war gleichzeitig Worker 3 UND Aggregator. Das führte zu:
1. **Self-Bias bei der Synthese** — Aggregator liest eigenen Entwurf
2. **Geringe Diversität** — Alle 3 Worker aus chinesischen Labs (DeepSeek, Alibaba, Z.ai)

### Lösung
Worker 3 ersetzt durch `mistral-large-3:675b` (Mistral, Frankreich):
- Europäisches Lab → kulturelle Perspektivenvielfalt
- 675B Parameter → vergleichbare Größenklasse
- Komplementäre Stärke: flüssige Textgenerierung, kreative Ansätze
- Kein Self-Bias mehr — Aggregator liest nur fremde Entwürfe

### Neue Konfiguration
| Rolle | Modell | Herkunft | Schwerpunkt |
|-------|--------|----------|-------------|
| Aggregator | `glm-5.2` | Z.ai (China) | Synthese, Neutralität |
| Worker 1 | `deepseek-v4-pro` | DeepSeek (China) | Deep Reasoning, Code |
| Worker 2 | `qwen3.5:397b` | Alibaba (China) | Logik, Mathe, multilingual |
| Worker 3 | `mistral-large-3:675b` | Mistral (Frankreich) | Kreativität, Sprachnuancen, europäische Perspektive |

### Test-Anpassungen (Pitfall #7 validiert)
Nach der Config-Änderung mussten folgende Test-Dateien aktualisiert werden:
- `test_config.py` — `worker_models` Assertion (1 Zeile)
- `test_pipeline.py` — 5 Test-Funktionen: `test_pipeline_all_ok_moa` (Responses + glm_calls 2→1), `test_pipeline_degradation_one_ok`, `test_pipeline_total_failure_raises` (fail-Set + glm-5.2), `test_pipeline_concat`, `test_pipeline_passes_worker_extra_body`
- `test_modelcheck.py` — `workers` Liste im `test_run_check_first_run`

**Wichtig:** `test_pipeline_all_ok_moa` änderte auch die Aggregator-Call-Erwartung von 2→1, da glm-5.2 nicht mehr als Worker läuft.

---

## Ollama Cloud Pro — Vollständiger Modellkatalog (Stand 2026-07-16)

18 Modelle verfügbar:

```
deepseek-v4-flash        gpt-oss:120b            minimax-m2.5
deepseek-v4-pro          gpt-oss:20b             minimax-m2.7
gemma4:31b               kimi-k2.5               minimax-m3
glm-5.1                  kimi-k2.6               mistral-large-3:675b
glm-5.2                  kimi-k2.7-code          nemotron-3-nano:30b
                                                 nemotron-3-super
                                                 nemotron-3-ultra
                                                 qwen3.5:397b
```

### Auswahlkriterien für Worker-Modelle
1. **Diversität** — Verschiedene Entwicklungsteams (verschiedene Länder/Labs)
2. **Architektur-Vielfalt** — Dense vs. MoE reduziert Groupthink
3. **Größenklasse** — Worker sollten vergleichbar groß sein (kein 20B neben 675B)
4. **Kein Self-Bias** — Aggregator-Modell darf nicht in der Worker-Liste stehen
5. **Kulturelle Diversität** — Nicht alle Worker aus demselben Land/Lab

### Abgelehnte Kandidaten für Worker 3 (mit Begründung)
| Modell | Warum nicht |
|--------|-------------|
| `nemotron-3-ultra` | NVIDIA — weniger bekannt für Sprachqualität; eher Tech-Fokus |
| `gpt-oss:120b` | Nur 120B — deutlich kleiner als die anderen Worker |
| `kimi-k2.7-code` | Moonshot — wieder chinesisch, würde Diversitätsproblem nicht lösen |
| `minimax-m3` | MiniMax — wieder chinesisch, gleiche Groupthink-Gefahr |
---

## Ausbau zum Rat der Sieben (2026-08-09)

Die Auswahl aus dieser Session gilt weiter — sie wurde von 3 auf 7 Sitze
erweitert und um Rollen ergaenzt. Details in `rat-der-sieben.md`.

### Was aus den Erkenntnissen oben uebernommen wurde

| Erkenntnis | Umsetzung |
|-----------|-----------|
| Self-Bias: Aggregator darf nicht Worker sein | `test_aggregator_never_sits_on_the_council` prueft beide Profile |
| `glm-5.2` zeigte den geringsten Self-Bias | bleibt Aggregator im VPS-Profil |
| Diversitaets-Prinzip (Labs, Architekturen) | `test_every_seat_comes_from_a_distinct_lab` — 7 Sitze, 7 Labs |
| Synthesizer soll staerker sein als die Worker | unter Claude Code aggregiert Opus 5 |
| Prompt-Falle "Aggregator" ist mehrdeutig | in `selfeval.py` immer als "Aggregator im Rat der Sieben" formuliert |

### Neu belegte Sitze aus dem Katalog

Vier Modelle, die im 3-Worker-Setup abgelehnt worden waren, sitzen jetzt im
Rat — die Ablehnungsgruende von damals gelten bei sieben Sitzen nicht mehr:

| Modell | Damals abgelehnt weil | Warum jetzt drin |
|--------|----------------------|------------------|
| `nemotron-3-ultra` | "eher Tech-Fokus" | genau richtig fuer den Skeptiker-Sitz |
| `gpt-oss:120b` | "nur 120B, zu klein" | Groessenklasse zaehlt weniger als die eigenstaendige OpenAI-Lineage; passt zum Pragmatiker |
| `kimi-k2.6` | "wieder chinesisch" | bei 7 Sitzen ist ein weiteres Lab ein Gewinn, kein Diversitaetsverlust |
| `minimax-m3` | "wieder chinesisch" | dito; besetzt auf dem VPS den Sitz des Strategen |

`gemma4:31b` bleibt draussen: 31B neben 397B und 675B bricht die
Groessenklasse zu deutlich. Kandidat fuer ein Sparprofil, siehe
`templates/custom_profile.py`.

### Verfuegbarkeits-Check deckt jetzt beide Profile ab

`modelcheck.WATCHED_MODELS` enthaelt alle Modelle beider Profile plus die
HTTP-Aggregatoren — nicht mehr nur die drei Worker der laufenden Maschine.
Faellt ein Modell aus dem Katalog, nennt die Warnung das betroffene Profil.
