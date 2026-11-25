# nc-database-editor – Projektnotizen & Konzept

Stand: 2026-11-20 · Status: **Planung, noch keine Implementierung**

## 1. Ziel (Anforderungen wie besprochen)

- Python-Tool zur Pflege einer **Nukliddatenbank**: lesen, durchsuchen, ändern.
- Versioniert mit git, später auf GitHub; soll später in **NucOffice** aufgenommen werden.
- **Plotten** ausgewählter Größen gegen sinnvolle Achsen (Z, N, A, …), z. B. Massendefekt-Plot.
  Die gnuplot-Vorlage `plotmass.gp` + `nuclide_masses.csv` sind nur Anregung (CSV ungeprüft);
  Werte sollen aus den Primärquellen kommen.
- Die Datenbank wird von anderen Tools **gelesen**: plotSPE, plotRDE/radonlab, ActivityPartitioner.
- **Herkunft (Quelle) jedes Wertes** speicherbar. Herkunft der Excel-Files klärt der Nutzer noch.
- **Leicht erweiterbar** um neue Nuklid-Eigenschaften.
- **Prompt-Gammas separat** speichern (stören sonst die Auswertung normaler Zerfallsspektren,
  stehen aber für Prompt-Gamma-Spektren in plotSPE zur Verfügung).
- **Spezifikation** der Datenbank (`docs/NUCDB-SPEC.md`), die in den anderen Projekten eingelesen
  wird, damit alle Tools die DB konsistent nutzen.

## 2. Gesichtete Quelldaten (`db-source/`)

| Datei | Inhalt | Umfang | Bemerkungen |
|---|---|---|---|
| `Liste-Daten-Elemente.xls` | Z, Symbol, Name, Atomgewicht, therm. Einfangquerschnitt (Element) | 85 Elemente | **Z 84–89 und 91 fehlen** (Po, At, Rn, Fr, Ra, Ac, Pa) – relevant für Radon! 43 Zahlwerte als Text gespeichert. |
| `Liste-isotope-häufigkeiten.xls` | Isotop, Z, A, Häufigkeit %, σ(b), g-Faktor, N(gammas) | 287 Isotope, 83 Elemente | nur natürlich vorkommende Isotope |
| `Liste-Gammas-Zerfall.xls` | Zerfallsgammas von **Aktivierungsprodukten**: E(γ), σγ (partieller Querschnitt), T½, k0 | 3382 Linien, 124 Nuklide (Z 7–92) | siehe Hinweis unten |
| `Liste-promptgammas.xls` | Prompt-Gammas nach (n,γ): Target A, Produkt, E(γ), σγ, k0 | 31 616 Linien, 245 Produktnuklide (Z 1–92) | |
| `Nuklidkarte.pdf` | Karlsruher Nuklidkarte (Scan, 2007) | 1 Seite | **reines Rasterbild** (16224×11403 px, 350 dpi), kein Text extrahierbar |

### Einschätzung der Excel-Files

Format und Spalten (A=Target, Isotope=Produkt, T=`p`/`d`, Sigma, k0, „Text/Value/Uncertainty“)
entsprechen sehr wahrscheinlich der **IAEA-Datenbank „Database of Prompt Gamma Rays from Slow
Neutron Capture for Elemental Analysis“** (IAEA STI/PUB/1263, 2007, Choi/Firestone et al.,
Budapest-PGAA-Gruppe). → Vom Nutzer zu bestätigen; dann als Quelle eintragen.

**Wichtig für plotSPE:** Die Datei `Liste-Gammas-Zerfall.xls` enthält **keine Emissions­wahr­schein­lich­keiten pro Zerfall (Iγ)**,
sondern partielle Aktivierungsquerschnitte σγ (b) und k0-Faktoren – also Daten für die
Neutronenaktivierungsanalyse. Außerdem fehlen alle natürlichen Radionuklide, die für
Umwelt-/Radonspektren zentral sind (K-40, Pb-214, Bi-214, Pb-210, Pb-212, Tl-208, Ra-226, Cs-137, …).
→ Für normale Zerfallsspektren und Zerfallsketten braucht es eine **zusätzliche Quelle**
(Vorschlag: ENSDF / IAEA LiveChart, NUBASE2020, ggf. DDEP).

### Datenqualität / Import-Fallstricke

- Gemischte Typen: Zahlen teils als Float, teils als Text (`'27.20'`), teils leer.
- Isotopnamen mit Leerzeichen-Padding (`' 16-N '`, `'239-U '`) → normalisieren.
- Werte liegen dreifach vor: Originaltext mit Unsicherheit in Klammern (`787.2(6)`), Wert, Unsicherheit.
  → Originaltext beim Import mit speichern (Nachvollziehbarkeit), Wert/Unsicherheit numerisch.
- Halbwertszeiten als Text mit Einheit (`'1.69 MS'`, `'1.265E+9 Y'`) plus bereits in Sekunden.
- Zwei Header-Zeilen (Zeile 0 Gruppe, Zeile 1 Unterspalte).

### Nuklidkarte (PDF)

Rasterbild der Karlsruher Nuklidkarte – Werte nur per OCR zugänglich (kleine Schrift auf
farbigem Grund → fehleranfällig). Außerdem urheberrechtlich geschütztes Produkt.
**Empfehlung:** Massen, Halbwertszeiten, Zerfallsarten aus maschinenlesbaren, frei
zitierbaren Evaluationen importieren (**AME2020** für Massen, **NUBASE2020** für T½/Zerfallsarten/Isomere),
die Nuklidkarte nur zum stichprobenartigen Gegenprüfen nutzen.

### gnuplot-Vorlage `plotmass.gp`

- Rechnet `Z·m_p + N·m_n − M_atom` mit **Atom**masse aber **Proton**masse → die Elektronenmassen
  (Z·0.000549 u) fehlen; korrekt wäre `Z·m(¹H) + N·m_n − M_atom`.
- Üblicher und aussagekräftiger: **Bindungsenergie pro Nukleon B/A in MeV gegen A** (Fe/Ni-Maximum),
  zusätzlich Massenexzess gegen A/Z. Wird als Plot-Preset vorgesehen.
- `nuclide_masses.csv`: 74 stabile Nuklide, N+Z=A überall konsistent; Werte trotzdem nicht übernehmen.

## 3. Architektur-Vorschlag

### Speicherformat: SQLite (eine Datei)

- In Python-Standardbibliothek enthalten, von jeder Sprache lesbar, eine Datei zum Verteilen,
  Transaktionen, Views.
- Für git: binäre DB lässt sich schlecht diffen → zusätzlich deterministischer **Text-Dump**
  (CSV je Tabelle oder SQL) im Repo, der bei jedem Speichern/Release erzeugt wird (offene Frage F3).

### Datenmodell (Details in der Spezifikation)

- `elements`, `nuclides` (Z, A, Isomerzustand) als Stammdaten.
- **Skalare Eigenschaften generisch** in `nuclide_values` (Nuklid × Größe × Quelle), Größen in
  Registry-Tabelle `quantities` (Name, Einheit, Beschreibung). → Neue Eigenschaft = neuer Eintrag
  in `quantities`, **kein Schemaumbau**. Mehrere Werte aus verschiedenen Quellen möglich, einer
  davon `preferred`.
- Komfort-View `v_nuclides` pivotiert die bevorzugten Werte in Spalten (einfaches Lesen für Konsumenten).
- Linienlisten als eigene Tabellen: `decay_gamma_lines`, **`prompt_gamma_lines` (separat)**.
- `decay_modes` (Mutter → Tochter, Verzweigungsverhältnis) für Zerfallsketten (radonlab, ActivityPartitioner).
- `sources` (Zitat, URL, Version, Lizenz, Datei-Hash, Abrufdatum) – jede Datenzeile hat `source_id`.
- `change_log` – jede Änderung über das Tool wird protokolliert (wer, wann, alt → neu, Kommentar).
- `meta` mit `schema_version` (semver) für Kompatibilitätsprüfung der Konsumenten.

### Python-Paket

```
nc-database-editor/
  src/nucdb/          # Bibliothek: Lesen/Schreiben, Nuklidnamen-Parser, Einheiten
    importers/        # je Quelle ein Importer (iaea_pgaa_xls, ame2020, nubase2020, livechart …)
    plotting/         # matplotlib-Plots + Presets
    cli.py            # Kommandozeile
    gui/              # Editor-Oberfläche (Toolkit offen, siehe F1)
  data/nucdb.sqlite   # erzeugte DB (oder als Release-Asset)
  data/dump/          # Text-Dump für git-Diffs
  db-source/          # Rohdaten (unverändert, nur gelesen)
  docs/
  tests/
```

- Konsumenten (plotSPE etc.) können **das Paket `nucdb` als Lese-Bibliothek importieren** statt
  SQL selbst zu schreiben → eine Stelle für Namensnormalisierung, Einheiten, Filter.
  Die Spezifikation beschreibt trotzdem die SQL-Ebene (für Nicht-Python-Nutzung).
- Importe sind **reproduzierbar**: DB lässt sich jederzeit aus `db-source/` + Importern neu bauen;
  manuelle Korrekturen landen als eigene Quelle („manual“, mit Kommentar) und überleben Neuimporte.

### Funktionen des Tools (Entwurf)

- Browsen/Suchen/Filtern (Nuklid, Element, Energiefenster, Mindestintensität).
- Bearbeiten mit Pflichtangabe der Quelle, Änderungsprotokoll, Undo über change_log.
- Peak-Identifikation: „welche Linien liegen bei E ± ΔE?“ – getrennt nach Zerfall/Prompt.
- Plotten: beliebige Größe X gegen Y aus `v_nuclides`; Presets: B/A vs A, Massenexzess,
  Nuklidkarte (N–Z, eingefärbt nach Zerfallsart oder log T½), Häufigkeiten, Querschnitte.
  Export PNG/PDF/SVG + Daten-CSV (auch gnuplot-tauglich).
- Import/Export: CSV, JSON; Validierung (N+Z=A, Häufigkeitssumme je Element ≈ 100 %,
  Intensitäten ≤ 1, Einheitenprüfung).

## 3a. Entscheidungen (2026-11-20, Runde 2) – haben Vorrang vor Abschnitt 3

- **Name:** NucDB. **Lizenz Code:** GPL-3.0. **GUI:** PySide6 (wie NucOffice, s. `../NucOffice/PLAN.md`).
  **Doku:** HTML.
- **Quellen:** AME2020 (Massen), NUBASE2020 (T½, Zerfallsarten, Isomere), IAEA LiveChart/ENSDF
  (Iγ pro Zerfall, Zerfallsketten) werden eingebunden. Die PGAA-Excel-Files liefern nur
  Prompt-Gammas, NAA-Daten (σγ, k0), Häufigkeiten und Element-Querschnitte; fehlende
  Zerfallsdaten/Elemente kommen aus den neuen Quellen.
- **Speicherformat: JSON** statt SQLite – Ordner mit einer JSON-Datei pro Datenart, ein Datensatz
  pro Zeile (git-diffbar, mit jedem Editor bearbeitbar). Details in `NUCDB-SPEC.md` v0.2.
  Die Lese-API darf intern einen Cache/Index bauen, das ist kein Speicherformat.
- **Prompt-Gammas** in eigener Datei `prompt_gamma_lines.json`, wird nur bei Bedarf geladen.
- **511 keV und 1022 keV** (sowie Escape-Peaks, Pb-Röntgenfluoreszenz) in `special_lines.json`.
- **Keine Umgebungsvariable:** Fundort = Pfad aus Tool-Einstellung → NucOffice-Datenordner →
  mitgelieferte Momentaufnahme im Paket. NucOffice übernimmt die Verteilung (muss dort in
  `PLAN.md` ergänzt werden: Registry-Eintrag für Daten bzw. „Daten-Paket“).
- **Keine Benutzerverwaltung**, nur Befugte bearbeiten; Änderungsprotokoll ohne Benutzerfeld.
- **Nuklidkarte:** Es gibt eine Textfassung (keine Texterkennung nötig). Wegen Datenbankrecht
  (§ 87a ff. UrhG) aber **nicht als Massenquelle** verwenden, nur für Stichproben-Gegenprüfung.
- **gnuplot-Vorlage** korrigiert: Wasserstoff-Atommasse statt Protonenmasse.

### Erkenntnisse aus den Konsumenten-Projekten

- **plotSPE** hat `plotspe/core/data/nuclides.json` (Format `plotspe-nuclides-v1`) mit
  **DDEP**-Daten (LNHB Lara): T½ und Gammalinien ≥ 0.5 %, Intensitäten in %.
- **ActivityPartitioner** hat `activity_partitioning/data/nuclides.json` (T½ + Zerfallswege mit
  Anteilen, stabile Endprodukte ausdrücklich), Nutzer können in der GUI eigene Nuklide anlegen
  (`user_db_path()`, Umgebungsvariable `ACTPART_DB`). Wird als PyInstaller-Build verteilt.
- **radonlab** (`radonEYE/src/radonlab/physics/constants.py`) hat Halbwertszeiten (Rn-222, Pb-212)
  fest im Code.
→ Alle drei sollen später auf NucDB umgestellt werden; Migrationspfad für eigene Nutzer-Nuklide
  nötig (s. Fragen).

## 4. Offene Fragen (an Nutzer)

Stand Runde 2 – erledigt: F1 (PySide6-GUI), F3 (JSON in git, s. u.), F4 (ja), F6 (NucOffice),
F7 (keine Benutzer), F8 (NucDB, GPL-3.0, HTML-Doku). Neue/offene Fragen siehe Abschnitt 6.

### Alte Fragen (Runde 1)

- **F1** Was ist NucOffice technisch (Python? GUI-Toolkit – PySide6/Qt, Tkinter, Web)? Soll der
  Editor eine GUI bekommen oder reicht zunächst Bibliothek + CLI?
- **F2** Herkunft der Excel-Files – IAEA PGAA-Datenbank 2007? (Vermutung, s. o.)
- **F3** Git-Strategie: SQLite-Datei ins Repo + Text-Dump, oder DB nur als Release-Asset?
- **F4** Zusätzliche Quellen einbinden (AME2020, NUBASE2020, ENSDF/LiveChart für Iγ pro Zerfall
  und Zerfallsketten)? Ohne diese fehlen Radon-Folgeprodukte komplett.
- **F5** Welche Daten brauchen plotSPE, radonlab, ActivityPartitioner konkret (z. B. Röntgenlinien,
  Annihilationslinie, Summenpeaks, Dosiskoeffizienten, Alpha-Energien für radonlab)?
- **F6** Wo soll die DB bei den Konsumenten liegen (Umgebungsvariable, NucOffice-Konfig, mitgeliefert)?
- **F7** Wer editiert – nur du, oder mehrere Personen (Bedarf an Benutzernamen/Review im change_log)?
- **F8** Paket-/Repo-Name: `nucdb`? Lizenz des Repos? Englische oder deutsche Doku/Oberfläche?

## 3b. Entscheidungen (2026-11-20, Runde 3) – Design steht in `NUCDB-SPEC.md` v0.3

- G1 **DDEP bevorzugt**, sonst ENSDF/LiveChart (Feld `decay_source` je Nuklid).
- G2 **Overlay** für Nutzereinträge, gemeinsam für alle Tools. Von Beginn an wird eine
  **umfangreiche Offline-DB** mitgeliefert.
- G3 Daten unter **CC BY 4.0**, Code unter GPL-3.0.
- G4 PGAA-Excel **auf Eis**: Die Quelle bekommt `redistributable: false`, `db-source/` steht in
  `.gitignore`, und `prompt_gamma.json` bleibt in der verteilten DB vorerst leer
  (freie Alternative prüfen: IAEA EGAF).
- G5 **Alle NUBASE2020-Nuklide**, Zerfallsstrahlung ab 0,1 % Intensität.
- G6 Spezifikation als Markdown **und** als HTML in der Doku.
- G7 Alpha, Beta (Endpunkt = E_max, plus mittlere Energie, Übergangstyp für LSC-Spektrenform),
  Konversions- und Auger-Elektronen, Röntgen: **alles aufnehmen**, jeweils in eigener Datei.
- G8 Editor-GUI mit PySide6. Die Lese-Bibliothek kommt nur mit der Standardbibliothek aus und
  lädt Dateien erst bei Bedarf.
- **Karlsruher Nuklidkarte: komplett weggelassen.**
- Verteilung: Die Spezifikation deckt beides ab – Verteilung durch NucOffice und eine
  Momentaufnahme im Paket. Was genutzt wird, entscheidet sich später.
- Git: Repo lokal initialisiert, `origin` = `git@github.com:symbio-n0mad/NucDB.git`.
  Noch kein Commit und kein Push.

## 6. Offene Fragen (Runde 2) – erledigt durch 3b

- **G1 DDEP:** plotSPE nutzt schon DDEP (Goldstandard für Gammaspektrometrie). DDEP als bevorzugte
  Zerfallsquelle für die ~220 dort evaluierten Nuklide, LiveChart/ENSDF für den Rest?
- **G2 Eigene Nuklide der Nutzer** (ActivityPartitioner erlaubt das): Zentrale DB schreibgeschützt +
  lokale „Ergänzungsdatei“ pro Nutzer, die die Lese-API darüberlegt?
- **G3 Lizenz der Daten:** Daten separat unter CC BY 4.0 (Code GPL-3.0) mit Quellenliste?
- **G4 PGAA-Excel:** Herkunft (IAEA 2007?) und Weitergabe-Erlaubnis klären, bevor die DB mit diesen
  Daten öffentlich auf GitHub liegt.
- **G5 Umfang:** alle ~3400 Nuklide aus NUBASE oder nur Nuklide mit T½ > Grenze / nur relevante?
  (Größe der Zerfallslinien-Datei: alle ≈ 10–20 MB, Schnitt ≥ 0.1 % deutlich kleiner.)
- **G6 Spezifikation:** als Markdown belassen (gut für andere Projekte/Claude lesbar) und zusätzlich
  als HTML in die Doku übernehmen?
- **G7 Weitere Strahlungsarten:** Alpha-Energien/-Intensitäten (radonlab: Po-218/Po-214/Po-212?),
  Beta-Endpunktenergien, Röntgenlinien gleich mit aufnehmen?
- **G8 Pakete:** `nucdb` (schlanke Lese-Bibliothek, keine GUI-Abhängigkeit) und Editor-GUI im selben
  Repo als Extra `nucdb[gui]` – einverstanden?

## 5. Nächste Schritte (wenn Umsetzung startet)

1. Fragen F1–F8 klären, Spezifikation auf v1.0 heben.
2. `git init`, Paketgerüst, GitHub-Repo verknüpfen.
3. Schema + Migrationen, Importer IAEA-PGAA (4 Excel-Files).
4. Importer AME2020/NUBASE2020 (+ ENSDF/LiveChart falls gewünscht).
5. Lese-API + CLI, Plot-Presets, dann Editor/GUI.
6. Spezifikation in plotSPE / radonlab / ActivityPartitioner einspielen.

## 7. Ergänzung (2026-11-20, Runde 4): Einheiten

- Man soll Halbwertszeiten und Zerfallskonstanten in beliebigen gängigen Einheiten eingeben und
  anzeigen können.
- **Zuständig ist das Paket `nucdb` (`nucdb.units`)**, nicht jedes Tool einzeln. In der DB bleibt
  alles in festen Einheiten (T½ in s). Details: `NUCDB-SPEC.md` Abschnitt 6a (Spec v0.4).
- Die bestehenden Einheiten-Module in ActivityPartitioner und plotSPE werden bei der Umstellung
  ersetzt. Sie sind brauchbare Vorlagen (Dezimalkomma, Einheitentabellen).

## 8. Etappenplan (Stand 2026-11-23)

1. **Etappe 1 – Grundlage (erledigt):** Paketgerüst (`pyproject.toml`, GPL-3.0, Daten CC BY 4.0),
   `nucdb.names` (Nuklidnamen), `nucdb.units` (Einheiten), `nucdb.fileformat` (kanonisches JSON),
   Lese-API `NucDB` mit Overlay (`db.user`), Validierung, CLI `nucdb`, Grunddatenbank in
   `src/nucdb/data/` (Elemente, Größen, Sonderlinien 511/1022 keV, Escape, Pb-Röntgen), Tests.
2. **Etappe 2 – Importer AME2020 + NUBASE2020 (erledigt):** 4454 Nuklide (253 stabil, 896 Isomere),
   Massen, Bindungsenergie, Q-Werte, T½, Spin/Parität, Häufigkeiten, 7369 Zerfallsarten.
   `nucdb import amdc2020 src/nucdb/data --src db-source/amdc2020 --download`.
   Isomer-Regel T½ ≥ 1 ms (gebräuchliche Namen). 16 Warnungen der Prüfung sind Eigenheiten der
   NUBASE-Daten (z. B. Verzweigungssumme ≠ 100 % bei Pt-182, Zn-54).
3. **Etappe 3 – Importer DDEP + IAEA LiveChart (erledigt):**
   - DDEP (Lara-Archiv): 251 Nuklide (davon 17 nur aus Mutter-Dateien, z. B. Th-227, I-132, U-233),
     T½, Zerfallsarten, Gamma/Röntgen, Alpha. α-Anteile in Lara gekürzt → als Rest berechnet.
     Jahresdefinition DDEP = tropisches Jahr (aus Jahres- und Sekundenangaben bestätigt).
   - ENSDF über LiveChart-API (8902 Abfragen, Zwischenspeicher `db-source/livechart/`): alle Nuklide
     mit T½ ≥ 1 s, Gamma/Röntgen ≥ 0,1 %, Alpha, Beta⁻/⁺ (Endpunkt, Mittel, Übergangstyp),
     Elektronen. Isomere über Anregungsenergie bzw. Halbwertszeit zugeordnet.
   - Gesamt: ≈ 96 000 Gamma-/Röntgenlinien, 18 000 Beta-Zweige, 24 000 Elektronen-, 1700 Alphalinien;
     Datenbank 32 MB (JSON). Neuaufbau: `nucdb build src/nucdb/data --src db-source`.
   - Peak-Suche mit Bewertung (Intensität × Abstand), Kandidatenfilter, ANN-Linien ausgeblendet.
   - 28 Warnungen der Prüfung = Eigenheiten der Quellen (Verzweigungssummen, Intensitäten > 100 %).
4. **Etappe 4 – PGAA-Excel, nur lokal (erledigt):** `nucdb build db-local --src db-source --local`
   ergänzt 31 616 Prompt-Gammas, 3382 NAA-Aktivierungslinien (eigene Datei `activation_gamma.json`),
   σ/g-Faktor/Häufigkeit von 287 Isotopen und Atomgewicht/σ von 85 Elementen. Quelle `PGAA-XLS` mit
   `redistributable: false`; `nucdb validate --distributable` verhindert die Weitergabe. Häufigkeiten
   bleiben aus NUBASE bevorzugt. Sobald die Herkunft geklärt ist: Quelle umbenennen/freigeben.
5. **Etappe 5 – Editor-GUI (PySide6) (erledigt):** `nucdb editor` bzw. `nucdb-editor` (Extra `gui`).
   - Nuklidliste mit Suche (Name, Element, `Z=`, `A=`), Detailansicht mit Werten, Zerfallswegen und
     allen Strahlungsarten (wahlweise alle Quellen), Peak-Suche, Quellen, Änderungsprotokoll.
   - Ziel wählbar: **Ergänzungsdatenbank** (eigene Werte, Linien, Nuklide über `db.user`) oder
     **zentrale Datenbank** mit Quellenpflicht. Zentrale Änderungen gehen über den Kurationsordner
     `curation/` (`nucdb.curation`), werden sofort angewandt und bei `nucdb build` erneut – sie
     überstehen also jeden Neuaufbau. Entfernen braucht eine Begründung (`removals.json`).
   - Overlay-Einträge lassen sich mit einer echten Quelle in die zentrale Datenbank übernehmen
     (eigene Nuklide samt Werten, Zerfallswegen und Linien).
   - Nicht weitergebbare Quellen gelangen nie in eine weitergebbare Datenbank (auch nicht beim Build).
   - Spezifikation unverändert (1.1): Kurationsordner ist internes Pflegeformat.
   - **Eigene Nuklidkarte** (2026-11-25): Viewer aus `nebenprojekte/show-pdf.py` als
     `nucdb.gui.chartviewer` übernommen (Deep-Zoom-Kacheln, nur sichtbare Kacheln im Hintergrund
     laden). Kacheln im Benutzer-Cache statt neben der PDF, Aufbau in eigenem Thread mit
     Fortschrittsanzeige (Karlsruher Karte 16224 × 11403 px: ≈ 30 s einmalig, 74 MB). Kalibrierung
     je **Abschnitt**, weil große Karten aus versetzten Streifen bestehen (Karlsruhe: z. B. Streifen
     ab La, Z = 57); danach springt die Karte zum gewählten Nuklid, und ein Klick wählt das Nuklid
     im Editor. Mitgeliefert wird keine Karte (Abschnitt 2, Nuklidkarte).
6. **Etappe 6 – Plots:** B/A, Massenexzess, Nuklidkarte (N–Z), freie X/Y-Wahl; Export.
7. **Etappe 7 – HTML-Doku, Release, Umstellung der Konsumenten** (plotSPE, radonlab, ActivityPartitioner).

## 9. Spezifikation 1.0 (2026-11-24)

- `docs/NUCDB-SPEC.md` ist als **1.0** festgeschrieben (Zusagen in Abschnitt 10), dazu
  `docs/NUCDB-INTEGRATION.md` mit den Umstellungsschritten für plotSPE, ActivityPartitioner,
  radonlab, das LSC-Tool und NucOffice. HTML-Fassung: `docs/html/` (`tools/build_docs.py`).
- Neu vor dem Festschreiben: `isomer_feeding.json` (297 Fütterungen aus der ENSDF-Niveaubilanz,
  z. B. Mo-99 → Tc-99m 87,8 %), automatisch in `decay_modes()`/`chain()` angewandt.
- Lizenz entschieden (2026-11-24): alles GPL-3.0-or-later, auch plotSPE (Sebastian hat zugestimmt).
- Offen: erster Push und Release-Tag `v1.0.0` (Tools binden `nucdb @ git+…@v1.0.0` ein).

## 10. Spezifikation 1.1 (2026-11-24)

- Wunsch aus plotSPE (werkstatt/VORMERKUNGEN.md): gefundene Peaks als eigene Linien speichern.
  Format konnte das schon (Overlay darf alle Dateien enthalten); ergänzt wurde nur die Schreib-API:
  `db.user.add_gamma`/`remove_gamma`, allgemein `add_emission`/`remove_emission`, `emissions`.
- Dazu Sperre gegen gleichzeitiges Schreiben (`.lock`, `OverlayLockedError`) und
  `overlay_changed()`/`reload_if_changed()` für laufende GUIs.
- Voll kompatibel zu 1.0 (MINOR); Tools binden künftig `@v1.1.0` ein.
