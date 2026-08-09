# Rat der Sieben — Designentscheidungen

Nachfolger des `multiai`-Skills (3 Worker, ein Profil, keine Rollen).
Was sich geaendert hat und warum.

---

## 1. Warum sieben statt drei

Drei Modelle liefern drei Meinungen; ob sie sich widersprechen, ist Zufall.
Sieben Sitze mit **festgelegten Rollen** garantieren, dass Widerspruch im
Verfahren steckt: der Skeptiker *muss* Gegenargumente suchen, der Pragmatiker
*muss* nach der einfacheren Loesung fragen. Der Aggregator bekommt dadurch
verwertbaren Dissens statt sieben Varianten derselben Antwort.

Preis: Latenz. Ollama Cloud Pro haelt drei Modelle gleichzeitig, also laeuft
der Rat in drei Wellen (~4-10 Min statt ~1-3 Min). Deshalb bleibt der Skill fuer
triviale Fragen ausdruecklich gesperrt.

---

## 2. Zwei Diversitaets-Achsen

| Achse | Umsetzung | Datei |
|-------|-----------|-------|
| Modell | 7 Labs, 3 Laender, Dense und MoE gemischt | `profiles.py` |
| Rolle | 7 Lens-System-Prompts, paarweise disjunkt | `profiles.py` |

Die Rollen sind der billigere und robustere Hebel: sie funktionieren auch,
wenn der Katalog schrumpft und zwei Sitze auf dasselbe Modell fallen. Der Test
`test_each_seat_gets_its_own_lens` haelt fest, dass die sieben Sitz-Prompts
tatsaechlich verschieden beim Provider ankommen.

`--no-lenses` schaltet die Rollen ab — nuetzlich, um zu messen, wie viel die
Rollen gegenueber reiner Modell-Diversitaet beitragen.

---

## 3. Aggregator je Umgebung

| Profil | Aggregator | Mechanik |
|--------|-----------|----------|
| `claude` | Opus 5 | **in-process** — die Engine gibt einen Synthese-Auftrag auf stdout aus, Claude Code liest und synthetisiert |
| `vps` | `glm-5.2` | **HTTP** — regulaerer Chat-Completion-Call gegen Ollama Cloud |

Auf dem Hermes VPS gibt es nur Ollama, also muss der Aggregator dort ein
Ollama-Modell sein. `glm-5.2` bleibt gesetzt: in der Vorgaenger-Session zeigte
es den geringsten Self-Bias bei Modell-Empfehlungen (siehe
`moa-model-selection.md`).

Unter Claude Code ist das staerkste verfuegbare Modell Opus 5 — und es ist
bereits da. Ein HTTP-Call dorthin waere ein zweiter Key, zusaetzliche Kosten
und ein schwaecheres Ergebnis als das Modell, das die Sitzung ohnehin fuehrt.

### Konsequenz: der Brief ist ein Auftrag, keine Antwort

Im `claude`-Profil ist die stdout-Ausgabe **Material fuer Opus 5**, nicht das
Endergebnis. `Result.needs_external_synthesis` und das JSON-Feld
`needs_external_synthesis` machen das maschinenlesbar; `render_brief()`
schreibt die Anweisung zusaetzlich in Klartext an den Anfang der Ausgabe.

Das ist die groesste Fehlerquelle des Designs: reicht ein Agent den Brief roh
an den Nutzer durch, sieht dieser einen Prompt statt einer Antwort. SKILL.md
warnt deshalb an zwei Stellen davor.

Absicherung fuer den Zweifelsfall: `--profile claude --strategy moa` wird von
`MultiAIConfig.validate()` mit einer erklaerenden Fehlermeldung abgelehnt,
statt still einen Call an ein Modell namens `claude-opus-5` gegen Ollama zu
schicken.

---

## 4. Sitzbesetzung

```
Analytiker   deepseek-v4-pro       DeepSeek   CN   Deep Reasoning
Ingenieur    qwen3.5:397b          Alibaba    CN   Code, Mathe
Skeptiker    nemotron-3-ultra      NVIDIA     US   breites Faktenwissen
Stratege     glm-5.2 / minimax-m3  Z.ai/MiniMax CN langer Kontext
Pragmatiker  gpt-oss:120b          OpenAI     US   kompakt, direkt
Erklaerer    mistral-large-3:675b  Mistral    FR   fluessige Sprache
Querdenker   kimi-k2.6             Moonshot   CN   unkonventionell
```

Der Sitz des Strategen ist der einzige Unterschied zwischen den Profilen:
`glm-5.2` aggregiert auf dem VPS und darf dort nicht mitreden (Self-Bias),
unter Claude Code aggregiert Opus 5 und `glm-5.2` wird als Sitz frei.
`minimax-m3` rueckt auf dem VPS nach. Erzwungen durch
`test_aggregator_never_sits_on_the_council`.

### Bekannte Schwaeche: Laenderverteilung

4 von 7 Sitzen stammen aus chinesischen Laboren. Das ist keine Design-Absicht,
sondern die Zusammensetzung des Ollama-Cloud-Katalogs: von neun Laboren mit
Flaggschiff-Modellen sind fuenf chinesisch. Die Alternative waere, kleinere
Modelle aufzunehmen (`gemma4:31b`, 31B) und damit die Groessenklasse zu
brechen — dafuer ist der Diversitaetsgewinn zu gering. Wird im Katalog ein
weiteres westliches Flaggschiff verfuegbar, gehoert es auf den Sitz des
Querdenkers.

---

## 5. Quorum

`quorum_k` steht auf **4** — die Mehrheit von sieben. Unterhalb davon
synthetisiert der Aggregator trotzdem, aber `Result.degraded` markiert den
Lauf (Feld `used_quorum`, dessen Name genau umgekehrt klingt, bleibt fuer
bestehende Aufrufer erhalten). Frueher lag die Schwelle bei 2 von 3.

Wichtig: das Quorum blockiert nichts. Es gibt in jedem Fall eine Antwort — die
Markierung dient der Transparenz, nicht der Ablaufsteuerung.

---

## 6. Parallelitaet

`max_parallel` (Default **3**) begrenzt die gleichzeitigen Sitze
client-seitig. Ohne diese Grenze gehen auf Ollama Cloud Pro alle sieben
Anfragen gleichzeitig raus, vier davon warten server-seitig in der
Warteschlange — und laufen dabei gegen den Client-Timeout von 240 s, obwohl
das Modell nie ein Problem hatte.

Auf einem Plan mit mehr Slots: `--max-parallel 7`.

---

## 7. Solo-Modus (`--strategy seats`)

Kein Netz, kein Key, trotzdem sieben Blickwinkel: Opus 5 beantwortet die Frage
nacheinander aus jeder Rolle und synthetisiert anschliessend.

Das ist ehrlich schwaecher als der echte Rat — ein Modell kann seine eigenen
blinden Flecken nicht durch Rollenspiel beheben. Deshalb verlangt
`render_seats()` ausdruecklich, dem Nutzer den Solo-Modus offenzulegen.

Der Modus existiert, weil der haeufigste Ausfall nicht "ein Modell ist weg"
ist, sondern "die ganze Cloud ist nicht erreichbar" — abgelaufener Key,
gesperrter Egress, Netzausfall auf dem VPS.

---

## 8. Migration vom alten `multiai`

| Alt | Neu |
|-----|-----|
| 3 Worker, keine Rollen | 7 Sitze mit Rollen |
| `DEFAULT_WORKER_MODELS` in `config.py` | `profiles.py`, deklarativ je Profil |
| Aggregator immer `glm-5.2` | je Profil; `claude` nutzt Opus 5 in-process |
| `quorum_k=2` | `quorum_k=4` |
| Strategien `moa`, `concat` | zusaetzlich `brief`, `seats` |
| `Draft(model, content, ok, error, latency_s)` | zusaetzlich `role`, `seat`, `label` |
| `modelcheck` prueft 3 Worker | prueft alle Modelle beider Profile |

`run_multiai(frage)` ohne Config funktioniert unveraendert — laeuft jetzt
allerdings im `claude`-Profil und liefert einen Brief statt einer fertigen
Antwort. Wer das alte Verhalten will:

```python
run_multiai(frage, config=MultiAIConfig.from_profile("vps"))
```

---

## 9. Selbstbewertung als Abnahmetest

`--self-eval` baut aus `SKILL.md`, `profiles.py`, `config.py`, `pipeline.py`
und `council.py` eine Bewertungsfrage mit sieben festen Pruefachsen und legt
sie dem Rat vor.

Damit ist die Abnahme des Skills ein Lauf des Skills: faellt der Rat aus, faellt
es beim Test auf. Und die Kritik kommt aus sieben unabhaengigen Blickwinkeln
statt aus dem Kopf dessen, der den Skill gebaut hat.

Die Bewertungsachsen stehen in `selfeval.py:EVAL_AXES` und sind bewusst
unangenehm formuliert ("erzeugen die Rollen-Prompts nur Scheindiversitaet?") —
eine Selbstbewertung, die nur Lob produziert, ist wertlos.

Ergebnis des ersten Laufs: `selbstbewertung-2026-08-09.md`. Sechs Befunde
wurden daraus umgesetzt, darunter der Umschlag fuer fremde Modell-Ausgaben
(Abschnitt 10) und das Ende des String-Slicings an den Synthese-Regeln.

---

## 10. Beitraege sind Daten, keine Anweisungen

Im `brief`-Modus liest Claude Code die Ausgaben von sieben fremden Modellen —
in einer Umgebung mit Werkzeugzugriff. Ein manipuliertes Modell koennte dort
Anweisungen platzieren, die als Auftrag gelesen werden.

Drei Lagen dagegen:

1. `AGGREGATOR_RULES` Regel 6 — gilt auf beiden Synthesewegen, auch beim
   HTTP-Aggregator auf dem VPS.
2. `render_brief()` setzt die Beitraege in einen
   `<untrusted_council_data>`-Block mit vorangestellter Warnung.
3. SKILL.md wiederholt es fuer den Fall, dass ein Agent nur die Doku liest.

Der VPS-Pfad ist weniger exponiert, weil `glm-5.2` keine Werkzeuge bedient —
die Regel gilt dort trotzdem, damit beide Wege identisch begruendet sind.

Nicht abgedeckt: ein Beitrag, der den Nutzer direkt taeuscht, statt den
Aggregator zu steuern. Dagegen hilft nur Regel 1 (jeden Beitrag kritisch
pruefen) und der Umstand, dass sieben Modelle selten dieselbe Falschaussage
teilen.
