---
name: multiai
description: >
  Beantwortet eine Frage mit 3 KI-Modellen gleichzeitig (Mixture-of-Agents) auf
  Ollama Cloud Pro und synthetisiert EINE bessere Antwort. Verwende diesen Skill
  AUTOMATISCH bei schwierigen, wichtigen oder mehrdeutigen Fragen, wo die
  kollektive Staerke mehrerer Modelle gewuenscht ist — auch ohne expliziten
  Befehl. Bei explizitem "/multiai", "frag mehrere Modelle", "Multi-AI", "MoA",
  "mehrere KIs" oder "zweite Meinung von anderen Modellen" immer verwenden.
user-invocable: true
argument-hint: <frage> [--strategy moa|concat] [--show-drafts] [--stream]
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

## Wann AUTOMATISCH verwenden (ohne expliziten Befehl)

Setze diesen Skill eigenstaendig ein, wenn DIESE Kriterien erfuellt sind:

- **Komplexe technische Fragen** — Architektur-Entscheidungen, Trade-offs,
  "welcher Ansatz ist besser fuer X", Multi-Step-Reasoning
- **Mehrdeutige oder umstrittene Themen** — bei denen verschiedene Modelle
  unterschiedliche Perspektiven bieten koennten (China/US/Europa)
- **Wichtige Entscheidungen** — mit dauerhaften Konsequenzen (Infrastruktur,
  Sicherheit, Kosten, Design-Architektur)
- **Fragen mit mehreren gueltigen Antworten** — bei denen die Synthese
  verschiedener Meinungen einen echten Mehrwert bietet
- **Tiefe Analyse / Erklaerungen** — bei denen umfassendes Reasoning
  mehrerer Modelle qualitativ besser ist als eine Einzelantwort

## Wann explizit verwenden (User-Befehl)

Immer, wenn der User sagt: `/multiai`, "frag mehrere Modelle", "Multi-AI",
"MoA", "mehrere KIs", "zweite Meinung von anderen Modellen"

## Wann NICHT verwenden

- Triviale Fragen (z.B. "wie heisst die Hauptstadt von Frankreich")
- Einfache Lookups, Definitionen, Faktenwissen
- Code-Schreiben / Datei-Edits / Ausfuehren von Befehlen — da ist ein
  einzelnes Modell schneller und ausreichend
- Wenn Geschwindigkeit wichtiger als maximale Qualitaet ist
- Bei Follow-Up-Fragen in einer laufenden Konversation, die sich auf
  Kontext beziehen, den nur das aktuelle Modell hat

## Latenz-Erwartung

~1–3 Minuten (3 Worker mit xhigh-Reasoning parallel + Synthese).
Den User bei automatischem Einsatz KURZ informieren:
"Diese Frage ist komplex genug fuer eine Multi-Modell-Synthese — das dauert ~1-3 Min."

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

## Installation / Update auf VPS

- Siehe `references/vps-github-deployment.md` fuer Anleitung zum Klonen, Pushen
  und Loesen von Auth-Problemen (SSH-Deploy-Keys, Security-Scanner, Git-Identity).