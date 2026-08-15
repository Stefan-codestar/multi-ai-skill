from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def offline_catalog(monkeypatch):
    """Haelt die Katalog-Aufloesung aus der Testsuite heraus.

    ``run_multiai`` loest Modellnamen gegen den Ollama-Katalog auf. Ohne diese
    Sperre wuerde die Suite echte HTTP-Anfragen stellen: langsam, abhaengig vom
    Netz, und die Ergebnisse haengen davon ab, welche Tags der Anbieter heute
    gerade fuehrt. Eine leere Menge bedeutet "Katalog unbekannt" — die
    konfigurierten Namen bleiben unangetastet.

    Tests, die die Aufloesung selbst pruefen, reichen ihren Katalog direkt an
    ``resolve``/``resolve_all`` und sind davon nicht betroffen.
    """
    monkeypatch.setattr("multiai.pipeline.load_catalog", lambda *a, **kw: set())
