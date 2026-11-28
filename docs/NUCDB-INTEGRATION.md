# NucDB einbinden – Anleitung für die Tools

**Zu NucDB-Spezifikation 1.2** · Stand 2026-11-26

Diese Datei sagt jedem Tool, **was es ändern muss**, um seine Nukliddaten aus NucDB zu beziehen.
Das Format selbst beschreibt `NUCDB-SPEC.md`; beide Dateien gehören zusammen.

> Für Claude Code in einem Tool-Projekt: Lies zuerst `NUCDB-SPEC.md` (mindestens Abschnitte 1–5, 9
> und 10), dann hier „Für alle Tools“ und den Abschnitt deines Tools. Die Umstellung ist eine
> Änderung am Programm und läuft nach den Regeln des jeweiligen Projekts (in plotSPE: als Auftrag
> durch die Werkstatt).

---

## 1. Für alle Tools

### 1.1 Abhängigkeit

Das Paket heißt `nucdb` (Python ≥ 3.11, keine weiteren Abhängigkeiten). Es enthält die Lese-API
**und** die komplette Datenbank (≈ 3 MB als Wheel). Ein Tool mit dieser Abhängigkeit funktioniert
ohne weitere Einrichtung.

| Wann | Eintrag in `pyproject.toml` bzw. `requirements.txt` |
|---|---|
| sobald NucDB auf GitHub veröffentlicht ist (empfohlen) | `nucdb @ git+https://github.com/symbio-n0mad/NucDB.git@v1.2.0` |
| bis dahin, lokal auf dem Entwicklungsrechner | `pip install -e /pfad/zu/nc-database-editor` (nicht in die Abhängigkeitsliste schreiben) |

Immer auf ein **Release-Tag** festlegen (`@v1.2.0`), nicht auf `main`. Ein Update auf `v1.x` ist
nach Spezifikation 10 ohne Codeänderung möglich.

### 1.2 PyInstaller-Builds

Die Datenbank liegt als Paketdaten in `nucdb/data/*.json`. PyInstaller nimmt sie nur mit, wenn
man es ausdrücklich sagt:

- Kommandozeile: `--collect-data nucdb`
- `.spec`-Datei: `from PyInstaller.utils.hooks import collect_data_files` und
  `datas += collect_data_files("nucdb")`

Prüfen im gebauten Programm: `NucDB().location` muss auf `…/nucdb/data` zeigen, und
`len(NucDB().nuclides())` muss 4454 ergeben.

### 1.3 Datenbank öffnen

```python
from nucdb import NucDB
db = NucDB()                      # Fundort automatisch (Spezifikation 2)
db = NucDB(pfad_aus_einstellungen) # wenn der Nutzer eine andere Datenbank gewählt hat
```

- **Einmal** pro Programmlauf öffnen und das Objekt weiterreichen; die Dateien werden beim ersten
  Zugriff gelesen und zwischengespeichert. Der erste Zugriff auf alle Gammalinien dauert ~1,5 s.
- Eine **Einstellung „Nukliddatenbank“** (Pfad, leer = automatisch) anbieten. Damit kann der Nutzer
  z. B. eine lokale Datenbank mit Prompt-Gammas (`db-local/`) wählen.
- In „Über …“ bzw. der Hilfe anzeigen, **welche** Datenbank geladen ist: `db.location`,
  `db.data_version`.
- Fehler abfangen: `IncompatibleSchemaError` (Datenbank zu neu/alt – verständliche Meldung),
  `UnknownNuclideError` (`KeyError`), `NuclideNameError`.

### 1.4 Quellen nennen (Pflicht)

Die Daten stehen unter **CC BY 4.0** und verlangen Namensnennung. Jedes Tool, das Werte anzeigt
oder exportiert, nennt in „Über …“ oder der Hilfe:

> Nukliddaten: NucDB (CC BY 4.0), nach DDEP (LNHB), ENSDF (IAEA LiveChart), NUBASE2020 und AME2020.

Die genauen Zitate liefert `db.source(key).citation`, die Quelle eines Wertes
`nuclid.preferred("half_life_s").source` bzw. `linie.source`. Wo es passt (Tooltip, Export-Kopf),
die Quelle des einzelnen Wertes mit ausgeben.

### 1.5 Halbwertszeiten und Einheiten

- Intern immer **Sekunden** verwenden: `n.half_life_s`, `n.decay_constant("1/s")`.
- Eingabe von Halbwertszeiten (oder Zerfallskonstanten) durch Nutzer:
  `units.parse_quantity(text, "half_life").value` – versteht `"65,94 h"`, `"5.27 a"`,
  `"2.1e-6 1/s"`, Unsicherheiten in Klammern.
- Anzeige: `n.format_half_life("auto")` oder `units.format_time(s, einheit, unsicherheit,
  decimal_comma=True)`.
- Jahr = 365,2422 d, festgelegt in NucDB. Eigene Jahreskonstanten entfernen.
- Zeitspannen zwischen zwei Daten (Referenzdatum → Messung) als Differenz von `datetime` in
  Sekunden rechnen, nie über „Anzahl Jahre“.

### 1.6 Ergänzungsdatenbank (Overlay) richtig nutzen

- Schreiben nur über `db.user` (Spezifikation 8 und 9): eigene Nuklide, Werte, Linien
  (`add_gamma`, `add_emission`) und ab 1.2 eigene Zerfallswege auch für zentrale Nuklide
  (`set_decays`; sie ersetzen alle zentralen Zweige des Nuklids, `DecayMode.user` ist dann wahr). Das Overlay ist **gemeinsam für alle Tools** – vor dem Schreiben
  beim Nutzer nachfragen bzw. deutlich anzeigen, was gespeichert wird.
- `OverlayLockedError` abfangen (anderes Programm schreibt gerade): Meldung „bitte gleich noch einmal
  versuchen“.
- GUIs rufen `db.reload_if_changed()` z. B. beim Aktivieren des Fensters auf, damit Einträge aus
  anderen Tools erscheinen.
- **Tests schreiben nie ins echte Overlay:** in Tests immer `NucDB(pfad, overlay=tmp_path / "ov")`
  oder `overlay=False` verwenden.

### 1.7 Was nicht geht

- Die zentrale Datenbank nicht verändern. Eigene Nuklide und Werte gehen über `db.user`
  (Ergänzungsdatenbank, gemeinsam für alle Tools, Spezifikation 8).
- Prompt-Gammas (`prompt_gamma.json`) nie mit Zerfallslinien mischen. In der verteilten Datenbank
  ist die Datei leer, bis die Quelle freigegeben ist.

### 1.8 Lizenz

NucDB (Code) steht unter **GPL-3.0-or-later**, die Daten unter **CC BY 4.0**. Entschieden
(2026-11-24): **alle Tools stehen unter der GPL**.

- **plotSPE** wechselt von MIT auf GPL-3.0-or-later; der Autor (Sebastian von Döllen) hat
  zugestimmt. Bei der Umstellung `LICENSE` ersetzen, die Lizenzangabe in `README.md` und
  `pyproject.toml` anpassen. Mitgelieferte MIT-Teile (z. B. pyGnuplot) bleiben mit ihrem
  MIT-Hinweis erhalten; MIT ist mit der GPL vereinbar.
- **ActivityPartitioner** und **radonlab** bekommen eine `LICENSE` mit GPL-3.0 und den Eintrag
  `license = "GPL-3.0-or-later"` in `pyproject.toml`.

---

## 2. plotSPE

Ziel: Die eigene Bibliothek `plotspe/core/data/nuclides.json` entfällt, die Linien kommen aus
NucDB. Die GUI und alle Aufrufer von `plotspe.core.nuclides` bleiben unverändert.

### 2.1 Heutiger Stand

- `plotspe/core/nuclides.py` lädt `data/nuclides.json` (Format `plotspe-nuclides-v1`): 20 Nuklide
  (Am-241, Cd-109, Co-57, Ba-133, Cs-137, Mn-54, Y-88, Zn-65, Co-60, Na-22, Eu-152, K-40, Ra-226,
  Pb-214, Bi-214, Ac-228, Pb-212, Bi-212, Tl-208, Tc-99m), DDEP-Gammalinien ≥ 0,5 %, Röntgen
  ausgeschlossen, Intensitäten in %.
- Benutzt von `gui_modern/decay_ui.py`, `calibration_ui.py`, `driver.py`, `app.py` über
  `load_nuclides()`, `match_lines()`, `assign_line()`, `line_data()`, `find_line()`,
  `suggest_calibration()`.
- `core/decay.py` hat `YEAR_DAYS = 365.2422` und `UNIT_SECONDS` für Halbwertszeiten.
- `core/units.py` rechnet **Spektrumsachsen** um (Kanal/Energie/Wellenlänge) – das ist kein
  Nukliddaten-Thema und bleibt unverändert.

### 2.2 Umstellung

1. **`load_nuclides()` aus NucDB füllen**, die Datenklassen `Nuclide`/`GammaLine` bleiben:
   ```python
   from nucdb import NucDB, units

   LIBRARY = ("Am-241", "Cd-109", "Co-57", "Ba-133", "Cs-137", "Mn-54", "Y-88", "Zn-65", "Co-60",
              "Na-22", "Eu-152", "K-40", "Ra-226", "Pb-214", "Bi-214", "Ac-228", "Pb-212",
              "Bi-212", "Tl-208", "Tc-99m")
   CHAIN = {"Ra-226": "Ra-226", "Pb-214": "Ra-226", "Bi-214": "Ra-226", "Ac-228": "Th-232",
            "Pb-212": "Th-232", "Bi-212": "Th-232", "Tl-208": "Th-232"}

   def _from_nucdb(db, name):
       n = db.nuclide(name)
       unit = units.auto_time_unit(n.half_life_s)          # z. B. "a", "d", "h"
       lines = tuple(GammaLine(name, g.energy_kev, g.energy_kev_unc, 100 * g.intensity,
                               None if g.intensity_unc is None else 100 * g.intensity_unc)
                     for g in db.gammas(name, radiation="G", min_intensity=0.005)
                     if g.intensity is not None)
       return Nuclide(name, n.half_life(unit), unit,
                      None if n.half_life_unc_s is None else units.from_base(n.half_life_unc_s, unit, "time"),
                      CHAIN.get(name), n.fields.get("ddep_reference") or n.preferred("half_life_s").source,
                      lines)
   ```
   Auswahlregel wie bisher: nur Gammas (`radiation="G"`), ≥ 0,5 %, Intensität in %. Die Liste
   `LIBRARY` und die Kettenzuordnung `CHAIN` bleiben plotSPE-Entscheidungen.
2. **Bibliothek erweiterbar machen (optional):** Jedes Nuklid aus NucDB kann in die Bibliothek
   aufgenommen werden (z. B. Auswahlliste mit Suche über `db.nuclides(stable=False)`).
3. **„Mögliche Nuklide“ der ROI-Karte (optional, Mehrwert):**
   `db.find_gammas(e, tol, nuclides=LIBRARY)` liefert zusätzlich Single-/Double-Escape-Peaks,
   511/1022 keV und Pb-Röntgenfluoreszenz (`LineMatch.kind`). `assign_line()` für die
   Zerfallskorrektur bleibt bei der eigenen, eindeutigen Logik.
4. **`core/decay.py`:** `YEAR_DAYS`/`UNIT_SECONDS` durch `nucdb.units` ersetzen
   (`units.to_base(wert, einheit, "time")`), damit die Jahresdefinition nur an einer Stelle steht.
5. **Prompt-Gamma-Modus (neu, später):** nur wenn der Nutzer ausdrücklich ein (n,γ)-Spektrum
   auswertet `db.prompt_gammas(...)`/`db.find_prompt_gammas(...)` verwenden. Ist die Liste leer
   (verteilte Datenbank), Hinweis: „Prompt-Gamma-Daten nur mit lokaler Datenbank verfügbar“.
6. `data/nuclides.json` löschen; PyInstaller-`.spec` um `collect_data_files("nucdb")` ergänzen
   (`packaging/plotspe.spec`).
7. **Gefundenen Peak einem Nuklid zuordnen (ab nucdb 1.1):** aus der ROI-Karte heraus, nach
   Bestätigung durch den Nutzer,
   `db.user.add_gamma(nuklid, energie_kev, energy_unc=…, intensity=… oder None, note="plotSPE, <Spektrum>")`.
   Die Linie erscheint danach in allen Tools als „eigener Eintrag“ (`line.user`) und kann mit
   `db.user.remove_gamma(nuklid, energie_kev)` wieder entfernt werden. Eigene Linien mit unbekannter
   Intensität (`None`) sind erlaubt; für die Zerfallskorrektur braucht eine Linie aber eine Intensität.

### 2.3 Was sich an Zahlen ändert

113 der 117 heutigen Linien sind identisch. Die Unterschiede sind neue DDEP-Evaluationen (2025):

| Nuklid | bisher (plotSPE) | NucDB (DDEP 2025) |
|---|---|---|
| K-40 | T½ 1,2504·10⁹ a; 1460,822 keV 10,55 % | 1,2522·10⁹ a; 10,34 % |
| Pb-212 | T½ 10,64 h; 115,2/238,6/300,1 keV 0,624/43,6/3,18 % | 10,630 h; 0,586/43,26/3,238 % |
| Cd-109 | 461,9 d | 461,885 d (DDEP gibt 1,2646 a an) |

Golden-Tests, die diese Werte enthalten, müssen nach der Umstellung bewusst neu eingefroren werden.

---

## 3. ActivityPartitioner

Ziel: Halbwertszeiten und Zerfallswege kommen aus NucDB; eigene Nuklide der Nutzer gehen in die
gemeinsame Ergänzungsdatenbank. Die Rechenlogik (`core.py`, `chains.py`) bleibt.

### 3.1 Heutiger Stand

- `activity_partitioning/nuclides.py`: Klasse `NuclideDB` lädt `data/nuclides.json`
  (`{"nuklide": [{"name", "halbwertszeit", "einheit", "notiz", "zerfaelle": [{"tochter", "anteil"}],
  "stabil"}]}`); Speicherort per `ACTPART_DB`, `--db` oder `user_db_path()` (gebaute Fassung).
- `Nuclide(name, half_life, unit, note, decays)` verlangt Anteile in (0, 1], Summe ≤ 1, und
  ausdrücklich stabile Endprodukte; fehlende Töchter sind ein Fehler.
- `chains.py` rechnet mit einer Zuordnung Name → `Nuclide`.

### 3.2 Umstellung

1. **`NuclideDB` auf NucDB umstellen** (gleiche Schnittstelle nach außen):
   ```python
   from nucdb import NucDB, units

   def nuclide_from_nucdb(db, name):
       n = db.nuclide(name)
       if n.stable:
           return Nuclide.stable_nuclide(n.name)
       unit = units.auto_time_unit(n.half_life_s)
       decays = tuple((m.daughter, m.effective_branching)
                      for m in db.decay_modes(n.name)
                      if not m.informational and m.daughter and m.effective_branching)
       note = ", ".join(sorted({m.mode for m in db.decay_modes(n.name) if m.mode}))
       return Nuclide(n.name, n.half_life(unit), unit, note, decays)
   ```
   **Immer `effective_branching` verwenden**, nie `branching` (Spezifikation 4.6): bei Teilzweigen
   wie β⁻n ist der Hauptzweig sonst doppelt gezählt, und die Zweige zu Isomeren (Mo-99 → Tc-99m
   0,878 / Tc-99 0,122; Spezifikation 4.6a) haben **nur** einen effektiven Anteil (`branching` ist
   dort `null`). Ergebnis für Mo-99: `(("Tc-99", 0.1222), ("Tc-99m", 0.8778))` – vergleichbar mit
   dem bisherigen Eintrag (0.1227 / 0.8773).
2. **Ketten:** `db.chain(start, min_branching=1e-6, include_unknown=False)` liefert alle Nuklide
   einer Kette in Reihenfolge Mutter vor Tochter (`chain.nuclides`) und die Zweige. Daraus die
   Zuordnung für `chains.py` bauen. `chain.unknown` (Tochter fehlt) und `chain.open_ends`
   (Zerfall unbekannt) als Warnung anzeigen – das entspricht der bisherigen Regel „fehlende
   Tochter ist ein Fehler“. Ab 1.2 mit `stable_above_s=nucdb.PRACTICALLY_STABLE_S` (10¹⁵ a):
   Dann endet z. B. die Np-237-Kette an Bi-209 (T½ 2·10¹⁹ a) statt bei Tl-205. Die so beendeten
   Nuklide stehen in `chain.practically_stable` und lassen sich in `chains.py` wie stabile
   Endprodukte behandeln; `nuclide.practically_stable()` prüft dieselbe Grenze. Alle Tools
   sollten diese Konstante verwenden, damit Ketten überall gleich enden.
3. **Eigene Nuklide:** Die GUI speichert neue/geänderte Nuklide mit
   `db.user.add_nuclide(name, half_life="65,94 h", decays=[("Tc-99m", 0.8773), ("Tc-99", 0.1227)])`
   bzw. `db.user.remove_nuclide(name)`; `nuclide.user` zeigt „eigener Eintrag“ an. Die Töchter
   müssen existieren (stabile Endprodukte gibt es in NucDB bereits alle).
   **Eigene Zerfallswege eines Nuklids, das in NucDB steht** (ab 1.2), z. B. die Mo-99-Verzweigung
   aus einem Zertifikat: `db.user.set_decays("Mo-99", [("Tc-99m", 0.8775), ("Tc-99", 0.1225)])`.
   Sie ersetzen alle zentralen Zweige dieses Nuklids, die Isomer-Aufteilung entfällt dafür (Isomere
   selbst angeben). Zurück zu den NucDB-Zweigen mit `db.user.remove_decays("Mo-99")`;
   `db.user.has_own_decays(name)` bzw. `m.user` zeigt „eigene Zerfallswege“ an.
4. **Migration:** Beim ersten Start einmalig die bisherige Nutzerdatei (`user_db_path()` bzw.
   `ACTPART_DB`) lesen und jedes Nuklid, das **nicht** in NucDB steht, mit `db.user.add_nuclide`
   übernehmen. Danach `ACTPART_DB`, `--db`, `user_db_path()` und `data/nuclides.json` entfernen.
5. **Einheiten:** Zeiteinheiten und das Lesen von Halbwertszeiten über `nucdb.units`
   (`TIME_UNITS`/`_lookup` für Zeiten ersetzen). Die Dezimaltrennzeichen-Logik der GUI (`i18n`)
   kann bleiben; `units.parse_quantity` versteht Komma und Punkt.
6. `build.py`: PyInstaller-Aufruf um `"--collect-data", "nucdb"` ergänzen.

### 3.3 Hinweise

- In NucDB stehen 4454 Nuklide; die Auswahl in der GUI braucht eine Suche/Filter
  (z. B. `db.nuclides(stable=False)` mit T½ ≥ 1 s).
- Zahlenwerte können von der bisherigen Datei abweichen (neuere Evaluationen). Tests mit festen
  Zahlen auf NucDB-Werte umstellen oder mit Toleranz prüfen.
- Halbwertszeiten zur Anzeige mit `nuclide.format_half_life()` ausgeben oder die
  Originalschreibweise der Quelle aus `nuclide.preferred("half_life_s").text` nehmen
  (z. B. „4.468E9(0.005E9) a“), nicht den in Jahre umgerechneten Wert mit allen Stellen. Ein Feld
  `half_life_text` gibt es nur in `activation_gamma.json` (NAA).

---

## 4. plotRDE / radonlab (`radonEYE`)

Ziel: Keine fest eingetragenen Halbwertszeiten mehr.

- `src/radonlab/physics/constants.py` enthält `RN222_HALF_LIFE_H = 3.8235 * 24` (Quelle: Pourkiaei
  et al. 2026) und `PB212_HALF_LIFE_H = 10.64`. Ersetzen durch:
  ```python
  from nucdb import NucDB
  _db = NucDB()
  RN222_HALF_LIFE_H = _db.nuclide("Rn-222").half_life("h")   # DDEP: 3,8232(8) d
  RN222_LAMBDA = _db.nuclide("Rn-222").decay_constant("1/h")
  PB212_HALF_LIFE_H = _db.nuclide("Pb-212").half_life("h")   # DDEP 2025: 10,630(7) h
  PB212_LAMBDA = _db.nuclide("Pb-212").decay_constant("1/h")
  ```
- Die Werte ändern sich leicht (Rn-222: 3,8235 → 3,8232 d; Pb-212: 10,64 → 10,630 h). Tests und
  Texte, die die Zahlen nennen (`decay.py`, `buildup.py`), anpassen.
- Für spätere Auswertungen stehen Alpha-Energien der Folgeprodukte bereit: `db.alphas("Po-218")`,
  `db.chain("Rn-222")`, `db.chain("Rn-220")`.

---

## 5. Geplantes LSC-Tool

- Beta-Spektren: `db.betas(name)` – je Zweig `energy_kev` = **Endpunktenergie E_max**,
  `mean_energy_kev`, `intensity` (pro Zerfall), `transition` (`A` erlaubt, `1U`, `2U`, `3U` …
  unique-verboten, `1NU` nicht-unique) für die Spektrenform; bei β⁺ zusätzlich `ec_intensity`.
- Konversions- und Auger-Elektronen: `db.electrons(name)` (`type` `CE`/`AU`, `shell`).
- Alphas: `db.alphas(name)`; Ketten und Gleichgewicht: `db.chain(...)` mit `effective_branching`.

---

## 6. NucOffice (optional)

Die Tools funktionieren ohne NucOffice, weil jedes die Datenbank über das Paket `nucdb` mitbringt.
NucOffice *kann* zusätzlich zentral aktualisieren:

- Eine neuere **verteilbare** Datenbank (geprüft mit `nucdb validate --distributable`) als Ordner nach
  `<NucOffice-Daten>/data/nucdb/` legen (Linux `~/.local/share/nucoffice/data/nucdb/`, Windows
  `%LOCALAPPDATA%\NucOffice\data\nucdb\`). Alle Tools nutzen sie dann automatisch (Spezifikation 2).
- Quelle der Aktualisierung: ein Release-Asset `nucdb-data-<data_version>.zip` des NucDB-Repositorys
  (wird mit dem ersten Release angelegt).
- Lokale Datenbanken mit nicht weitergebbaren Quellen (`db-local/`) **nie** verteilen.
- Registry-Eintrag für NucDB selbst: `entry = "nucdb"` (Kommandozeile); der Editor mit GUI folgt.

---

## 7. Abnahme je Tool

- [ ] `nucdb` als Abhängigkeit mit festem Tag; PyInstaller nimmt `nucdb/data` mit.
- [ ] Keine eigene Nukliddaten-Datei und keine fest eingetragenen Halbwertszeiten mehr.
- [ ] Ketten und Aktivitäten verwenden `effective_branching`.
- [ ] Halbwertszeiten intern in Sekunden; Ein-/Ausgabe über `nucdb.units`.
- [ ] Einstellung für einen eigenen Datenbankpfad; „Über …“ zeigt `db.location`, `db.data_version`
      und die Quellennennung (1.4).
- [ ] Prompt-Gammas nur im ausdrücklichen Prompt-Modus, leere Liste wird verständlich behandelt.
- [ ] Lizenz auf GPL-3.0-or-later umgestellt (1.8).
