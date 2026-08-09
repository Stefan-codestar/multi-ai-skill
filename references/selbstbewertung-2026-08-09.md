# Selbstbewertung des Rats der Sieben — 2026-08-09

Abnahmetest des fertigen Skills: der Rat bewertet den Rat.

```bash
python3 -m multiai --self-eval --strategy seats
```

**Modus:** Solo (`seats`) — ein Modell, sieben Blickwinkel.
**Aggregator:** Opus 5.
**Warum nicht der Vollmodus:** Gebaut wurde in einer Claude-Code-Web-Sandbox
ohne `OLLAMA_API_KEY`, in der `ollama.com` per Egress-Policy gesperrt ist
(403 auf CONNECT). Die sieben Sitze waren nicht erreichbar. Der Lauf mit
sieben echten Modellen steht noch aus — siehe "Offen" am Ende.

---

## Urteil

Der Ausbau von drei auf sieben Sitze traegt, weil die Diversitaet nicht allein
aus der Modellauswahl kommt: die Rollen erzwingen Widerspruch, den drei
Modelle mit identischem Prompt nur zufaellig produziert haetten. Die Trennung
der Aggregatoren ist richtig — auf dem VPS gibt es nur Ollama, unter Claude
Code waere ein HTTP-Call an ein schwaecheres Modell absurd, wenn Opus 5 die
Sitzung ohnehin fuehrt.

Der Preis ist real und wurde unterschaetzt: sieben Sitze bei drei Slots kosten
das Drei- bis Vierfache an Wartezeit, und der `brief`-Modus verlagert einen
Korrektheitsschritt aus dem Code in eine Instruktion, die ein Modell befolgen
muss. Beides ist vertretbar, aber nur mit den unten umgesetzten Absicherungen.

---

## Umgesetzt (aus dieser Bewertung)

### 1. Beitraege sind Daten, keine Anweisungen — Skeptiker

**Der schwerwiegendste Befund.** Im `brief`-Modus wandern die Ausgaben von
sieben fremden Modellen als Text in eine Umgebung mit Werkzeugzugriff. Ein
kompromittiertes oder manipuliertes Modell konnte dort Anweisungen platzieren,
die Claude Code als Auftrag liest. Der VPS-Pfad hat dieses Problem in dieser
Schaerfe nicht, weil `glm-5.2` keine Werkzeuge bedient.

Umgesetzt in `council.py`: die Beitraege stehen jetzt in einem
`<untrusted_council_data>`-Block mit vorangestellter Warnung; `aggregate.py`
erhielt Regel 6, die auf beiden Wegen gilt. SKILL.md warnt zusaetzlich.
Abgesichert durch `test_brief_wraps_contributions_in_an_untrusted_envelope`.

### 2. Synthese-Regeln wurden per String-Slicing zerschnitten — Ingenieur

`render_brief` und `render_seats` schnitten die Regeln mit
`AGGREGATOR_SYSTEM_PROMPT.rsplit("\n\n", 1)[0]` aus dem Prompt-String heraus.
Wer eine Regel anhaengt, verliert sie im Brief stillschweigend — kein Test
haette es bemerkt.

Umgesetzt: `AGGREGATOR_RULES` ist jetzt eine eigene Konstante, der
System-Prompt setzt sich daraus zusammen. Kein Slicing mehr. Abgesichert durch
`test_synthesis_rules_reach_both_paths_intact`.

### 3. `used_quorum` bedeutet das Gegenteil seines Namens — Analytiker

Das Feld ist `True`, wenn das Quorum **nicht** erreicht wurde. Aus dem
Vorgaenger uebernommen und dort schon irrefuehrend.

Umgesetzt: `Result.degraded` als sprechender Name. `used_quorum` bleibt fuer
bestehende Aufrufer erhalten.

### 4. Latenzangabe war zu optimistisch — Analytiker

SKILL.md nannte 3-8 Minuten. Rechnung: sieben Sitze bei `max_parallel=3` sind
drei Wellen, bei 240 s Timeout je Welle bis zu 12 Minuten. Korrigiert auf
~4-10 Min, Extremfall 12 Min.

### 5. `Seat.strength` war totes Feld — Pragmatiker

Wurde gesetzt, aber nirgends ausgegeben. Jetzt zeigt `--roster` Lab, Land und
Begruendung je Sitz.

### 6. Der Aggregator ist nicht garantiert Opus 5 — Stratege

`claude-opus-5` in der Config ist eine Bezeichnung, keine Durchsetzung —
aggregiert wird von dem Modell, das die Ausgabe liest. Laeuft Claude Code auf
Sonnet, aggregiert Sonnet. In SKILL.md jetzt ausdruecklich vermerkt.

---

## Offen — bewusst nicht umgesetzt

### Dissens-Modus statt Synthese — Querdenker

Die Synthese glaettet genau das weg, wofuer man sieben Modelle fragt. Ein
Modus, der nur ausgibt, **wo** der Rat auseinanderging (und wer welche Seite
vertrat), waere bei Entscheidungsfragen oft wertvoller als eine geglaettete
Antwort.

Aufwand: mittel — eine Strategie `dissens` plus ein Vergleichsschritt.
Nicht umgesetzt, weil ohne echten Sieben-Modell-Lauf nicht beurteilbar ist,
wie oft der Rat tatsaechlich auseinandergeht.

### Debatte statt Parallel-Fanout — Querdenker

Sitze nacheinander laufen lassen, jeder sieht die vorherigen Beitraege. Hoehere
Qualitaet, aber siebenfache Latenz statt dreifacher. Bei drei Slots
unwirtschaftlich.

### Modellkatalog altert — Stratege

Die Modellnamen sind fest verdrahtet, der Ollama-Katalog wechselt spuerbar
(`glm-5.1`→`5.2`, `kimi-k2.5`/`2.6`/`2.7`). `modelcheck` warnt, heilt aber
nicht. Naechster sinnvoller Schritt: bei fehlendem Modell einen Ersatz aus
demselben Lab vorschlagen. Aufwand: mittel.

### Wirkung der Rollen ist unbelegt — Analytiker

`--no-lenses` existiert, aber es gibt keinen Vergleichslauf. Ob die Rollen
mehr beitragen als die Modellauswahl, ist bisher Annahme. Ein A/B-Lauf
derselben Frage mit und ohne Rollen waere der erste echte Beleg — braucht
ebenfalls Modellzugang.

---

## Was der Rat ausdruecklich bestaetigt hat

- Der Aggregator gehoert nicht in den Rat (Self-Bias) — durch Test erzwungen.
- `max_parallel=3` ist kein Detail: ohne die Grenze laufen vier Anfragen in
  der Warteschlange in den Client-Timeout und sehen wie kaputte Modelle aus.
- Der Solo-Modus rechtfertigt seine ~40 Zeilen, weil der haeufigste Ausfall
  nicht ein einzelnes Modell ist, sondern der Zugang insgesamt.
- Das Uebergewicht chinesischer Labore (4 von 7) ist eine Eigenschaft des
  Katalogs, nicht des Entwurfs. Die Alternative — `gemma4:31b` neben 675B —
  bricht die Groessenklasse fuer wenig Gewinn.

---

## Offener Punkt fuer den Nutzer

Der Lauf mit sieben echten Modellen fehlt noch. Auf einer Maschine mit
`OLLAMA_API_KEY` und Netzzugang:

```bash
# Hermes VPS — glm-5.2 aggregiert, Ergebnis ist die fertige Bewertung
cd ~/.hermes/skills/multi-ai-skill && python3 -m multiai --self-eval --profile vps

# Claude Code — Opus 5 aggregiert
cd ~/.claude/skills/rat-der-sieben && python3 -m multiai --self-eval
```

Erst dieser Lauf zeigt, ob die sieben Sitze tatsaechlich auseinandergehen oder
ob die Rollen nur Scheindiversitaet erzeugen — die Frage, die diese
Selbstbewertung mangels Modellzugang nicht beantworten konnte.
