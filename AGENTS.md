# AGENTS.md — multi-ai-skill (Rat der Sieben)

## Zweck
Multi-AI-Gremium: stellt Fragen an sieben LLM-Sitze mit festen Rollen (Analytiker, Ingenieur, Skeptiker, Stratege, Pragmatiker, Erklaerer, Querdenker) und synthetisiert daraus eine Antwort mit erhaltener Dissens-Spannung.

## Commands
- Rat laufen lassen: `python3 -m multiai "<FRAGE>" --profile vps`
- Roster pruefen: `python3 -m multiai --roster`
- Modellverfuegbarkeit: `python3 -m multiai.modelcheck --force`
- Tests: `python3 -m pytest tests/ -x` (aus Repo-Root; venv: felix-venv)

## Constraints
- KEINE Secrets/API-Keys im Code oder Commit-History. Nutze `.env` (gitignored) — Beispiel-Struktur in `requirements-dev.txt`-Kommentar bzw. felix-Stack `.env`.
- Aggregator-Selbst-Bias-Schutz: Der Sitz "Stratege" darf im VPS-Profil NICHT vom Aggregator-Modell besetzt sein (glm-5.2 aggregiert dort -> minimax-m3 sitzt). Profill-Config nicht ohne Rat-Lauf aendern.
- Roster-Aenderungen (Modell-Swaps) nur mit Verfuegbarkeits-Check (`modelcheck --force`) und Commitment-Hash in der Commit-Message.
- Commit-Format: Conventional Commits (`feat:`, `fix:`, `chore:`)
- Sprache: Code-Kommentare englisch oder deutsch (bestehender Stil: gemischt), Commit-Messages englisch.

## Verweise
- Architektur/Roster-Profile: `multiai/` (Code), `SKILL.md` (Skill-Definition)
- Rat-Lauf-Logs + Commitments: `/home/hermes/workshop-tmp/commitments_rat.log` (VPS-lokal, nicht im Repo)