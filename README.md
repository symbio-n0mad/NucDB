# NucDB

Nukliddatenbank für die Tools von NucOffice (plotSPE, plotRDE/radonlab, ActivityPartitioner, LSC-Tool).

- **Daten** als lesbarer Ordner mit JSON-Dateien, jede Angabe mit Quelle
  (Format: [`docs/NUCDB-SPEC.md`](docs/NUCDB-SPEC.md), Spezifikation 1.1; Einbindung in die Tools:
  [`docs/NUCDB-INTEGRATION.md`](docs/NUCDB-INTEGRATION.md); HTML-Fassung in `docs/html/`).
- **Lese-API** `nucdb` ohne Abhängigkeiten außer der Python-Standardbibliothek (Python ≥ 3.11).
- **Einheiten** zentral in `nucdb.units`: Halbwertszeiten und Zerfallskonstanten in jeder gängigen
  Einheit eingeben und anzeigen.
- **Ergänzungsdatenbank** für eigene Einträge, gemeinsam für alle Tools.
- Prompt-Gammas getrennt von den Zerfallslinien.

Status: Spezifikation 1.1; Etappen 1–5 von 7 erledigt (Plots und Release folgen, siehe [`docs/KONZEPT.md`](docs/KONZEPT.md)). Die mitgelieferte
Datenbank enthält alle 4454 Nuklide aus NUBASE2020 mit Massen (AME2020), Halbwertszeiten,
Zerfallsarten sowie Gamma-, Röntgen-, Alpha-, Beta- und Elektronenstrahlung (DDEP, wo evaluiert,
sonst ENSDF über die IAEA LiveChart-API).

## Beispiel

```python
from nucdb import NucDB, units

db = NucDB()                                   # findet die Datenbank selbst
co = db.nuclide("60Co")
co.half_life("a"), co.decay_constant("1/h")
db.find_gammas(1332.5, tol_kev=1.0)            # Peak-Identifikation (ohne Prompt-Gammas)
db.chain("Rn-222")                             # Zerfallskette

units.parse_quantity("5,27 a", kind="half_life").value   # -> Sekunden
db.user.add_nuclide("Mo-99", half_life="65,94 h", decays=[("Tc-99m", 0.8773), ("Tc-99", 0.1227)])
```

## Kommandozeile

```
nucdb info
nucdb show Co-60
nucdb find 609.3 --tol 1.5
nucdb convert "3.8235 d" 1/h
nucdb validate
nucdb editor                 # Oberfläche, braucht: pip install 'nucdb[gui]'
```

## Editor und Pflege

Der Editor (`nucdb editor`) zeigt Nuklide, Werte, Zerfallswege und Linien mit ihren Quellen, sucht
Peaks und schreibt wahlweise in die eigene Ergänzungsdatenbank oder – mit Quellenpflicht – in die
zentrale Datenbank. Zentrale Änderungen landen im Ordner `curation/` und werden bei
`nucdb build` nach den Importern erneut angewandt; Einträge der Ergänzungsdatenbank lassen sich mit
einer echten Quelle übernehmen.

**Eigene Nuklidkarte:** NucDB liefert keine Nuklidkarte mit (Urheber- und Datenbankrecht). Eine
eigene (z. B. die Karlsruher Nuklidkarte als PDF) lässt sich im Editor unter „Nuklidkarte“ (Strg+K)
oder mit `nucdb-chart karte.pdf` anzeigen – auch riesige Scans flüssig, weil die Seite einmalig in
Kacheln zerlegt wird (`pip install 'nucdb[chart]'`, Kacheln im Benutzer-Cache). Nach dem Kalibrieren
(je Streifen der Karte zwei Nuklide anklicken) springt die Karte zum gewählten Nuklid, und ein Klick
in die Karte öffnet das Nuklid im Editor.

## Entwicklung

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

## Lizenz

Code: GPL-3.0-or-later (`LICENSE`). Daten: CC BY 4.0, mit Nennung der Primärquellen (`DATA-LICENSE.md`).
