# nc-database-editor

Python-Tool zur Pflege einer Nukliddatenbank (JSON-Ordner, siehe Spezifikation), später Teil von NucOffice; Konsumenten:
plotSPE, plotRDE/radonlab, ActivityPartitioner.

- Konzept, Quellanalyse, offene Fragen: `docs/KONZEPT.md`
- Schnittstellen-Spezifikation für Konsumenten: `docs/NUCDB-SPEC.md` (Änderungen dort immer mit
  Versionshistorie und Semver-Regel aus Abschnitt 4 pflegen)
- `db-source/` enthält Rohdaten (Excel .xls, Nuklidkarte als Rasterbild) – nur lesen, nie ändern.
  `.xls` braucht `xlrd`.
- Prompt-Gammas immer getrennt von Zerfallslinien halten.
- Code: `src/nucdb/` (Lese-API nur mit der Standardbibliothek; GUI später mit PySide6 als Extra `gui`).
  Grunddatenbank: `src/nucdb/data/` (wird mit `nucdb build-base` erzeugt, nach Datenänderungen
  `nucdb manifest` ausführen).
- Entwickeln: `.venv/bin/pip install -e '.[dev]'`, Tests: `.venv/bin/pytest -q`.
- `SCHEMA_VERSION` in `src/nucdb/schema.py` = Version der Spezifikation; beide zusammen ändern.
- Datenbank neu bauen: `nucdb build src/nucdb/data --src db-source` (verteilt) bzw.
  `nucdb build db-local --src db-source --local` (mit nicht weitergebbaren PGAA-Daten, nie ins Repo).
  Vor jeder Veröffentlichung: `nucdb validate src/nucdb/data --distributable`.
- Spezifikation ist 1.1 (`docs/NUCDB-SPEC.md`, Zusagen in Abschnitt 10): innerhalb 1.x nichts
  umbenennen/entfernen, nur ergänzen (MINOR). Bei jeder Änderung auch `docs/NUCDB-INTEGRATION.md`
  prüfen und `tools/build_docs.py` laufen lassen (HTML in `docs/html/`).
- Editor: `nucdb editor` (PySide6, `src/nucdb/gui/`). Zentrale Korrekturen nur über `curation/`
  (`nucdb.curation`, Quellenpflicht); `nucdb build` wendet `curation/` automatisch an.
- Status und Etappenplan: `docs/KONZEPT.md` Abschnitte 8 und 9.
