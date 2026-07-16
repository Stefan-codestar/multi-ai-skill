---
name: multiai
description: >
  Beantwortet eine Frage mit 3 KI-Modellen gleichzeitig (Mixture-of-Agents) auf
  Ollama Cloud Pro und synthetisiert EINE bessere Antwort. Verwende diesen Skill,
  wenn "/multiai", "frag mehrere Modelle", "Multi-AI", "MoA", "mehrere KIs" oder
  "zweite Meinung von anderen Modellen" gesagt wird, oder bei schwierigen/wichtigen
  Fragen, wo die kollektive Staerke mehrerer Modelle gewuenscht ist.
user-invocable: true
argument-hint: <frage> [--strategy moa|concat] [--show-drafts]
version: 0.2.0
author: AKINO
license: MIT
metadata:
  hermes:
    tags: [multi-model, moa, mixture-of-agents, ollama-cloud, ensemble]
---

# multiai — Mixture-of-Agents Antworten

Faechert eine Frage parallel an 3 LLMs auf und laesst ein Lead-Modell die
Antworten zu EINER hochwertigen Antwort synthetisieren.

- **Lead/Aggregator:** `glm-5.2` (Z.ai Flaggschiff, liest alle 3 Entwuerfe)
- **Worker (3, parallel, Ollama Cloud Pro, `reasoning_effort: xhigh`):**
  `deepseek-v4-pro` (DeepSeek), `nemotron-3-ultra` (NVIDIA), `mistral-large-3:675b` (Mistral)
- **Provider:** Ollama Cloud Pro — im Plan-Kontingent enthalten

## Wann verwenden
- Bei schwierigen, wichtigen oder mehrdeutigen Fragen
- Wenn explizit `/multiai`, "frag mehrere Modelle", "zweite Meinung", "MoA" gesagt wird
- NICHT fuer triviale Fragen (ein Modell reicht — spart Kontingent und Zeit)
- Latenz-Erwartung: ~1–3 Minuten (3 Worker mit xhigh-Reasoning parallel + Synthese)

## Woechentlicher Fallback-Check (PFLICHT bei jedem Einsatz)

Bevor die Engine startet, IMMER zuerst ausfuehren:

```bash
cd ~/.hermes/skills/multi-ai-skill && python -m multiai.modelcheck
```

- Output `Fallback-Check nicht faellig` -> ignorieren, normal weitermachen
- Output mit `AENDERUNGEN GEFUNDEN` / `WARNUNG:` / `FEHLER:` ->
  User aktiv informieren: kurz zusammenfassen was sich geaendert hat

## Ausfuehrung

```bash
cd ~/.hermes/skills/multi-ai-skill && python -m multiai "<FRAGE>"
```

Die finale, synthetisierte Antwort kommt auf stdout — an User weitergeben.

### Optionen
- Einzelantworten zeigen: `--show-drafts`
- Nur sammeln statt synthetisieren: `--strategy concat`
- Modelle ueberschreiben: `--models modell-a,modell-b --lead aggregator`
- Maschinenlesbar: `--json`
- **Live-Streaming:** `--stream` — synthetisierte Antwort erscheint Wort fuer Wort
  (Worker laufen weiterhin parallel; nur die Synthese wird gestreamt)
  ```bash
  cd ~/.hermes/skills/multi-ai-skill && python -m multiai "<FRAGE>" --stream
  ```
  Reduziert wahrgenommene Latenz drastisch. Siehe `references/streaming.md`
  fuer Details zur Implementierung (SSE-Parsing, Thinking-Model-Retry).

## Verhalten / Robustheit
- Worker-Timeout/Fehler -> wird uebersprungen, andere laufen weiter
- >=2 OK -> normale MoA-Synthese; 1 -> Degradationsmodus; 0 -> Aggregator antwortet allein
- Es gibt immer eine Antwort

## Voraussetzungen
- `OLLAMA_API_KEY` in `~/.env` (Format: `OLLAMA_API_KEY=dein-key`)
- Python >= 3.10, nur Stdlib (kein pip zur Laufzeit)
- Projektpfad: `~/.hermes/skills/multi-ai-skill/`
