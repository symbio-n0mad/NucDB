# NucDB – Spezifikation der Nukliddatenbank

**Version der Spezifikation: 1.1** · Stand 2026-11-24 · umgesetzt in `nucdb` 1.1
Projekt: NucDB (`github.com/symbio-n0mad/NucDB`) · Daten: CC BY 4.0 · Code: GPL-3.0-or-later

Dieses Dokument richtet sich an **Konsumenten** der Datenbank: plotSPE, plotRDE/radonlab,
ActivityPartitioner, das geplante LSC-Tool und NucOffice. Es kann in diesen Projekten direkt als
Umsetzungsvorgabe eingelesen werden. Es beschreibt das Format vollständig, sodass ein Tool die
Dateien auch ohne das Paket `nucdb` lesen kann.

> **Stand 1.0:** Format und Lese-API sind festgelegt (Zusagen in Abschnitt 10). Innerhalb von 1.x
> kommt nur Neues hinzu, nichts wird umbenannt oder entfernt. Was ein Tool konkret ändern muss, um
> NucDB zu nutzen, steht in `NUCDB-INTEGRATION.md`.

---

## 1. Überblick

- Die Datenbank ist ein **Ordner mit JSON-Dateien** (UTF-8). Es gibt kein Binärformat.
  Jede Datei lässt sich mit einem Texteditor lesen und notfalls bearbeiten.
- **Eine Datei pro Datenart.** Ein Tool lädt nur, was es braucht. Prompt-Gammas liegen in einer
  **eigenen Datei** und werden nie zusammen mit Zerfallslinien geladen.
- Jeder Wert und jede Linie nennt seine **Quelle**.
- Eine **umfangreiche Offline-Datenbank wird mitgeliefert**: alle 4454 Nuklide aus NUBASE2020 mit
  Massen (AME2020), Halbwertszeiten und Zerfallsarten sowie Zerfallsstrahlung (DDEP, wo evaluiert,
  vollständig; sonst ENSDF ab 0,1 % Intensität).
- Eigene Einträge der Nutzer liegen in einer **Ergänzungsdatenbank** (Overlay, Abschnitt 8).
  Sie gilt für alle Tools gemeinsam. Die zentrale Datenbank bleibt dabei unverändert.

## 2. Fundort der Datenbank

Die Lese-API sucht in dieser Reihenfolge und nimmt den ersten Treffer:

1. den Pfad, den das Tool ausdrücklich übergibt (z. B. aus seinen Einstellungen),
2. den gemeinsamen NucOffice-Datenordner `<NucOffice-Daten>/data/nucdb/`
   - Linux: `~/.local/share/nucoffice/data/nucdb/`, systemweit `/opt/nucoffice/data/nucdb/`
   - Windows: `%LOCALAPPDATA%\NucOffice\data\nucdb\`, systemweit `%ProgramFiles%\NucOffice\data\nucdb\`
3. die Momentaufnahme im Paket `nucdb` (`nucdb/data/`). Sie funktioniert auch ohne NucOffice und
   in PyInstaller-Builds.

Liegen mehrere Datenbanken vor, gewinnt nicht automatisch die neueste. Es gilt die Reihenfolge
oben. Die API meldet, welche Datenbank sie geladen hat (`db.location`, `db.data_version`).
Es gibt **keine Umgebungsvariable**.

**Verteilung:** Jedes Tool, das das Paket `nucdb` als Abhängigkeit hat, bringt die Momentaufnahme
(2.3) automatisch mit und funktioniert damit sofort. NucOffice *kann* zusätzlich eine neuere Datenbank
in den gemeinsamen Datenordner (2.2) legen; dann nutzen alle Tools diese, ohne neu installiert zu
werden. Beides ist mit dieser Reihenfolge abgedeckt.

## 3. Konventionen

### 3.1 Einheiten (fest, im Feldnamen erkennbar)

| Größe | Einheit | Feldnamen |
|---|---|---|
| Energie | keV | `*_kev` |
| Zeit, Halbwertszeit | s | `*_s` |
| Masse | u, **Atom**masse (inkl. Elektronen) | `*_u` |
| Massenexzess, Q-Wert, Bindungsenergie | keV | `*_kev` |
| Wirkungsquerschnitt | barn | `*_b` |
| Isotopenhäufigkeit | % (Atomprozent) | `*_percent` |
| Intensität, Verzweigung | **Bruchteil 0…1** | `intensity`, `branching` |

Intensitäten gelten immer **pro Zerfall des genannten Nuklids**. Die Verzweigung innerhalb einer
Kette ist nicht eingerechnet. Ein Beispiel: Tl-208 wird nur in rund 36 % der Zerfälle der
Th-232-Kette gebildet, das steckt nicht in seinen Linienintensitäten.

### 3.2 Unsicherheiten und Kennzeichen

In flachen Datensätzen (Linien, Zerfallsarten) heißen die Begleitfelder `<feld>_unc`,
`<feld>_flag` und `<feld>_text` (z. B. `branching_unc`, `branching_flag`). In den Wertobjekten von
`nuclides.json` (4.5) heißen sie kurz `unc`, `flag` und `text`.

- `<feld>_unc`: Standardunsicherheit 1σ, absolut, in der Einheit des Feldes.
  `null` heißt „unbekannt“.
- `<feld>_flag`, optional:
  - `"<"` oder `">"`: Ober- bzw. Untergrenze
  - `"~"`: Abschätzung
  - `"sys"`: aus Systematik abgeleitet
  - `"?"`: unsicher zugeordnet
- `<feld>_text`, optional: die Originalschreibweise der Quelle, z. B. `"5.2714(5) y"`.

### 3.3 Nuklidnamen

- Eindeutiger Schlüssel ist `(z, a, isomer)`.
  `isomer` ist 0 für den Grundzustand, 1 für m, 2 für m2 usw.
- Der kanonische Name lautet `<Symbol>-<A>[m[n]]`, z. B. `Co-60`, `Tc-99m`, `Hf-178m2`.
  Er ist **der Verweis zwischen allen Dateien**. Es gibt keine numerischen IDs.
- Die Lese-API akzeptiert auch `60Co`, `Co60`, `60-Co`, `CO-60` und `co 60`.
- **Isomere:** Als eigenes Nuklid gilt ein angeregter Zustand mit T½ ≥ 1 ms (oder ein stabiler,
  z. B. Ta-180m). Diese Zustände werden nach Anregungsenergie durchgezählt: `m`, `m2`, `m3` …
  Das ergibt die gebräuchlichen Namen: Ag-110m = 250 d, Lu-177m = 160 d, Kr-83m = 1,8 h,
  Ir-192m2 = 241 a. NUBASE zählt auch kürzere Zustände (ns, µs) mit; sein Buchstabe steht im
  Feld `nubase_state` (z. B. Ag-110m: `"n"`).

### 3.4 Dateiaufbau

Jede Datei hat diesen Aufbau:

```json
{"format": "nucdb/<dateiname>", "schema_version": "1.1.0",
 "records": [
{"...": "ein Datensatz pro Zeile"},
{"...": "..."}
]}
```

- Datensätze sind sortiert: Nuklide nach (z, a, isomer), Linien nach (Nuklid, Energie).
- Innerhalb eines Datensatzes sind die Schlüssel sortiert. `null`-Felder werden weggelassen,
  ein fehlendes Feld bedeutet also `null`.
- Der Editor schreibt immer genau diese Form. Dadurch zeigt git nur echte Änderungen an.

## 4. Dateien

| Datei | Inhalt | Laden |
|---|---|---|
| `manifest.json` | Versionen, Dateiliste mit SHA-256, Importparameter | immer |
| `sources.json` | Quellen | immer |
| `quantities.json` | Liste der skalaren Größen (Erweiterungspunkt) | immer |
| `elements.json` | Elemente | bei Bedarf |
| `nuclides.json` | Nuklide mit skalaren Werten | bei Bedarf |
| `decay_modes.json` | Zerfallsarten, Mutter → Tochter | bei Bedarf |
| `isomer_feeding.json` | Anteil der Zerfälle, der in einem Tochter-Isomer landet (Mo-99 → Tc-99m) | bei Bedarf |
| `decay_gamma.json` | Gamma- und Röntgenlinien, Annihilation | bei Bedarf |
| `decay_alpha.json` | Alpha-Linien | bei Bedarf |
| `decay_beta.json` | Beta⁻- und Beta⁺-Zweige (E_max, E_mittel) | bei Bedarf |
| `decay_electron.json` | Konversions- und Auger-Elektronen | bei Bedarf |
| `special_lines.json` | Linien, die zu keinem Nuklid gehören (511, 1022 keV …) | bei Bedarf |
| **`prompt_gamma.json`** | **Prompt-Gammas nach (n,γ), getrennt von allem anderen** | nur ausdrücklich |
| `activation_gamma.json` | Linien von Aktivierungsprodukten mit σγ und k0 (NAA), bezogen auf das Target | nur ausdrücklich |
| `changelog.json` | Änderungsprotokoll | nur Editor |

### 4.1 `manifest.json`

```json
{"format": "nucdb/manifest", "schema_version": "1.1.0", "data_version": "2026.11.0",
 "created_at": "2026-11-20T12:00:00Z", "license": "CC-BY-4.0",
 "import": {"min_intensity": 0.001, "min_intensity_sources": ["ENSDF-LiveChart"], "min_half_life_s": 1},
 "source_priority": ["DDEP", "ENSDF-LiveChart", "NUBASE2020", "AME2020"],
 "files": {"nuclides.json": {"sha256": "…", "records": 3340}}}
```

- `data_version` steigt bei jeder Datenänderung, Muster `JJJJ.MM.n`.
- `import.min_intensity` ist die Intensitätsschwelle, ab der Strahlung importiert wurde; sie gilt
  für die Quellen in `min_intensity_sources` (ENSDF). DDEP-Daten werden vollständig übernommen,
  Beta-Zweige immer. `min_half_life_s`: ENSDF-Strahlung nur für Nuklide mit T½ ≥ 1 s.
- `source_priority`: Reihenfolge der Quellen, falls die `decay_source` eines Nuklids für eine
  Datenart keine Daten hat (4.5).

### 4.2 `sources.json`

Felder je Quelle:

- `key`: eindeutiger Kurzname, z. B. `AME2020`, `NUBASE2020`, `DDEP`, `ENSDF-LiveChart`, `manual`
- `title`, `authors`, `publisher`, `year`, `version`, `url`, `doi`
- `license`: Lizenz bzw. Nutzungsbedingungen
- `citation`: der fertige Zitiertext
- `redistributable`: `true`/`false`. Quellen mit `false` kommen nur in lokale Builds, **nie in
  die verteilte Datenbank**. Das betrifft derzeit die PGAA-Excel-Files.
- `file_name`, `file_sha256`, `retrieved_at`, `notes`

### 4.3 `quantities.json`

Felder: `quantity`, `unit`, `dtype` (`real` | `int` | `text`), `description`.

Anfängliche Größen:

| quantity | Einheit | Herkunft |
|---|---|---|
| `mass_u` | u | AME2020 |
| `mass_excess_kev` | keV | AME2020 / NUBASE2020 |
| `binding_energy_per_nucleon_kev` | keV | AME2020 |
| `half_life_s` | s | DDEP, sonst NUBASE2020 |
| `level_energy_kev` | keV | NUBASE2020 (Isomere) |
| `spin_parity` | text | NUBASE2020 |
| `abundance_percent` | % | NUBASE2020 / IUPAC |
| `sigma_capture_b` | b | derzeit nur in lokalen Datenbanken (PGAA-Excel, 4.12) |
| `g_factor_westcott` | 1 | derzeit nur in lokalen Datenbanken (PGAA-Excel) |
| `resonance_integral_b` | b | vorgesehen, noch ohne Daten |
| `q_beta_minus_kev`, `q_alpha_kev`, `q_ec_kev` | keV | AME2020 |

Eine **neue Größe ist nur ein neuer Eintrag** in dieser Datei. Am Format ändert sich nichts.

### 4.4 `elements.json`

Felder: `z`, `symbol`, `name_en`, `name_de`, `source` (Quelle der Namen), optional `atomic_weight_u`,
`atomic_weight_u_unc`, `atomic_weight_text`, `sigma_capture_b`, `sigma_capture_b_unc`,
`sigma_capture_text`. Weil die Messwerte aus anderen Quellen stammen können als die Namen, hat jede
Wertgruppe ihr eigenes Quellenfeld: `atomic_weight_source`, `sigma_capture_source`.

### 4.5 `nuclides.json`

Beispiel (Zahlenwerte nur zur Veranschaulichung):

```json
{"name": "Co-60", "z": 27, "a": 60, "isomer": 0, "stable": false,
 "decay_source": "DDEP",
 "values": {
   "half_life_s": [{"value": 166344192, "unc": 12096, "source": "DDEP", "preferred": true},
                   {"value": 166338000, "unc": 24000, "source": "NUBASE2020"}],
   "mass_u": [{"value": 59.933816299, "unc": 4.6e-8, "source": "AME2020", "preferred": true}]}}
```

- `stable`: `true` bei stabilen Nukliden, also den Endprodukten von Zerfallsketten. Auch
  „beobachtungsstabile“ Nuklide, für die nur vermutete Zerfälle (`branching_flag: "?"`) bekannt sind,
  gelten als stabil; Ketten enden dort.
- Optionale Felder: `nubase_state`, `discovery_year`, `isomer_order_uncertain` (NUBASE), `ddep_reference`
  (Evaluator und Jahr), `ensdf_reference` (ENSDF-Bearbeiter und Stand).
- `decay_source`: die **bevorzugte Quelle für alle Zerfallsdaten dieses Nuklids**, also
  Zerfallsarten und alle `decay_*`-Linien. Vorgabe ist DDEP, sofern evaluiert, sonst
  ENSDF-LiveChart. Linien aus anderen Quellen bleiben zum Vergleich gespeichert, die API liefert
  sie aber nur auf Anfrage.
  Hat die `decay_source` für eine Datenart (z. B. Alpha-Linien) keine Daten, nimmt die API die
  erste vorhandene Quelle nach `manifest.source_priority`, sonst alphabetisch.
  Einträge aus der Ergänzungsdatenbank (Overlay) werden immer mitgeliefert.
- Ist nur ein Wert vorhanden, gilt er als bevorzugt, auch ohne `preferred`.
- `values`: Größe → Liste von Werten. Genau ein Wert ist `preferred`, die Felder sind die aus 3.2.

### 4.6 `decay_modes.json`

Felder:

- `parent`
- `mode`: in NUBASE-Schreibweise, also `B-`, `B+`, `EC`, `e+`, `A`, `IT`, `SF`, `p`, `2p`, `n`, `2n`,
  `2B-`, `B-n`, `B-2n`, `B-A`, `B+p`, `B-SF`, Clusterzerfälle wie `14C` …
  (`B+` umfasst in NUBASE β⁺ **und** EC.)
- `daughter`: Grundzustand der Tochter; `null` bei Spaltung (`SF`, `B-SF` …) und bei kombinierten
  Clusterzerfällen. IT führt zum Grundzustand desselben Nuklids.
- `branching`, `branching_unc` (Bruchteil), `branching_flag` (`?` unbekannt, `~`, `<`, `>`, `sys`),
  `q_value_kev`, `source`, optional `text` (Originalangabe).
- `parent_mode`: bei **Teilzweigen** der Hauptzweig, in dem sie enthalten sind. Beispiel Li-11:
  `B-` = 100 %, davon `B-n` = 86,3 % mit `parent_mode: "B-"`. EC bzw. e+ sind nur dann Teilzweig von
  `B+`, wenn `B+` schon (fast) alles umfasst (`B+=100;EC=60`), bei `EC=61;B+=39` sind es getrennte Zweige.

Die Summe der Hauptzweige (ohne `parent_mode`) je Mutter und Quelle ist ≈ 1 und wird geprüft,
sofern alle Anteile bekannt sind.
Eine fehlende Tochter ist ein Datenfehler. Sie gilt nicht stillschweigend als stabil.

**Effektiver Anteil** (berechnet die Lese-API als `effective_branching`): Anteil, der wirklich zur
angegebenen Tochter führt. Beim Hauptzweig werden die Teilzweige mit anderer Tochter abgezogen
(Li-11: `B-` → Be-11 effektiv 6 %). Teilzweige mit derselben Tochter wie ihr Hauptzweig sind nur
Information (`informational`) und zählen in Ketten nicht doppelt. Konsumenten, die Ketten oder
Aktivitäten rechnen, verwenden **immer** `effective_branching`.

### 4.6a `isomer_feeding.json`

NUBASE und DDEP nennen als Tochter nur den Grundzustand (Mo-99 → Tc-99 100 %). Welcher Anteil
tatsächlich im **Isomer** der Tochter landet, steht hier:

- `parent`, `mode` (Zerfallsart laut Quelle), `isomer` (z. B. `Tc-99m`),
- `fraction`: Anteil **aller** Zerfälle der Mutter, die das Isomer bevölkern (0…1),
- `method` (`ENSDF-Niveaubilanz`: direkte β/EC/α-Fütterung des Isomerniveaus + alle Übergänge, die
  dort enden, Gammaintensität × (1 + Konversionskoeffizient)), `source`.

Beispiele: Mo-99 → Tc-99m 0,878; Cs-137 → Ba-137m 0,947; Th-234 → Pa-234m 0,993;
Rb-83 → Kr-83m 0,743; Sb-125 → Te-125m 0,231.

Die Lese-API wendet die Fütterung in `decay_modes()` und `chain()` **automatisch** an: Der Zweig
zum Grundzustand wird um `fraction` verkleinert, und ein zusätzlicher Zweig zum Isomer erscheint
(`effective_branching = fraction`, Feld `isomer_feeding: true`, `branching: null`). Für Mo-99 liefert
`decay_modes()` also B- → Tc-99m 0,878 und B- → Tc-99 0,122. Bei eigenen Zerfallswegen aus dem
Overlay wird nichts aufgeteilt. Wer die Dateien ohne `nucdb` liest, muss diese Aufteilung selbst
vornehmen.

### 4.7 Zerfallsstrahlung (`decay_*.json`)

Gemeinsame Felder: `nuclide` (das **zerfallende** Nuklid), `energy_kev`, `energy_kev_unc`,
`intensity`, `intensity_unc` (pro Zerfall), `source`, sowie optional `_flag`-Felder.

| Datei | Zusätzliche Felder |
|---|---|
| `decay_gamma.json` | `radiation`: `G` (Gamma), `XK`/`XL` (Röntgen; `xray_line` in Schreibweise der Quelle, DDEP z. B. `Ka1`, `K'b1`, ENSDF z. B. `KA1`, `L`), `ANN` (511 keV aus β⁺, Intensität bis 2: zwei Quanten pro Positron). Optional: `origin` (aussendender Kern bzw. Atom), `energy_range_kev` [von, bis] bei Röntgengruppen, `multipolarity`, `conversion_coeff`, `decay_mode`. NAA-Daten stehen getrennt in `activation_gamma.json` (4.10) |
| `decay_alpha.json` | optional `daughter_level_kev`, `beta_delayed: true` (β-verzögerte „long-range“ Alphas, z. B. beim Bi-212-Zerfall aus angeregtem Po-212) |
| `decay_beta.json` | `type`: `B-` oder `B+`. **`energy_kev` ist die Endpunktenergie (= E_max)**, dazu `mean_energy_kev` (+ `_unc`), optional `transition` (ENSDF-Schreibweise: `A` erlaubt, `1NU` erstverboten nicht-unique, `1U`, `2U` … für Spektrenformen im LSC-Tool), `log_ft`, `daughter_level_kev`; bei β⁺ zusätzlich `ec_intensity` (EC-Anteil zum selben Niveau) |
| `decay_electron.json` | `type`: `CE` (Konversion) oder `AU` (Auger), `shell` (z. B. `K`, `L`, `KLL`, `KLX`). Intensitäten können über 1 liegen (mehrere Auger-Elektronen pro Zerfall) |

Röntgen- und Auger-Linien stammen von der Atomhülle der Tochter, werden aber beim zerfallenden
Nuklid geführt, so wie in DDEP und ENSDF.

Gammalinien werden vom angeregten Tochterkern ausgesandt (`origin`), gehören aber zum Zerfall des
genannten Nuklids (`nuclide`). Linien aus dem Zerfall von Folgenukliden stehen bei diesen, nie bei
der Mutter (Sr-90 hat keine Gammas; die 2186 keV gehören zu Y-90).

**Quellen der Zerfallsstrahlung:** DDEP (Lara-Dateien) liefert für die rund 250 dort evaluierten
Nuklide Gamma-, Röntgen- und Alphalinien sowie Zerfallsarten; diese Nuklide haben
`decay_source: "DDEP"`. Beta- und Elektronendaten fehlen in DDEP; für sie greift die Rückfallregel
(4.5) auf ENSDF. Alle anderen Nuklide bekommen ihre Strahlung aus ENSDF (IAEA LiveChart), ihre
Zerfallsarten aus NUBASE2020. Isomere werden über die Anregungsenergie des Mutterzustands zugeordnet.

### 4.8 `special_lines.json`

Diese Linien gehören zu keinem Nuklid, tauchen aber in Spektren auf. Felder:

- `kind`: `annihilation`, `sum`, `single_escape`, `double_escape`, `xray_fluorescence`, `backscatter`,
  `compton_edge`
- `energy_kev` (fester Wert) **oder** `offset_kev` (relativ zu einer Linie E)
- `origin`, `description`, `source`

| kind | Energie | Bedeutung |
|---|---|---|
| `annihilation` | 511.00 keV | Vernichtungsstrahlung |
| `sum` | 1022.00 keV | Summenpeak 2 × 511 keV |
| `single_escape` | E − 511 | Escape-Peak bei Paarbildung (E > 1022 keV) |
| `double_escape` | E − 1022 | Doppel-Escape-Peak |
| `xray_fluorescence` | Pb Kα1 74.97, Kα2 72.80, Kβ ≈ 84.9 keV | Röntgenfluoreszenz der Bleiabschirmung |
| `backscatter` | E / (1 + 2E/m_e c²), berechnet | Rückstreupeak |
| `compton_edge` | 2E² / (m_e c² + 2E), berechnet | Compton-Kante |

m_e c² = 510.99895 keV (CODATA 2018). Die Pb-Röntgenenergien stammen aus dem X-Ray Data Booklet (2009).
`backscatter` und `compton_edge` haben keine feste Energie; `nucdb.physics` berechnet sie.

### 4.9 `prompt_gamma.json` (getrennt)

Felder:

- `target`: das eingefangene Nuklid, z. B. `Fe-56`
- `product`: z. B. `Fe-57`
- `element`
- `energy_kev`, `energy_kev_unc`
- `sigma_partial_b`, `sigma_partial_b_unc`: elementarer partieller Querschnitt σγ
- `k0`, `k0_unc`
- `source`

Die bisherige Quelle (PGAA-Excel, Schlüssel `PGAA-XLS`) ist noch nicht zur Weitergabe freigegeben.
Bis zur Klärung ist diese Datei in der verteilten Datenbank **leer** und nur in lokalen Datenbanken
befüllt (4.12). Tools müssen mit einer leeren Datei umgehen können. Eine mögliche freie Quelle ist
IAEA EGAF.

### 4.10 `activation_gamma.json` (NAA)

Zerfallslinien von Aktivierungsprodukten, aber mit Werten **pro Target** statt pro Zerfall:
`target` (z. B. `Al-27`), `product` (`Al-28`), `element`, `energy_kev` (+ `_unc`), `sigma_partial_b`
(+ `_unc`, elementarer partieller Querschnitt σγ), `k0` (+ `_unc`), optional `half_life_s` und
`half_life_text` des Produkts laut Quelle, `source`. Für die Neutronenaktivierungsanalyse; die Linien
pro Zerfall stehen weiterhin in `decay_gamma.json`. Python: `db.activation_gammas(element="Al")`.

### 4.11 `changelog.json`

Felder: `changed_at`, `file`, `record`, `field`, `old`, `new`, `comment`.
Es gibt keine Benutzerverwaltung, nur Befugte bearbeiten die Datenbank.

### 4.12 Lokale Datenbanken und nicht weitergebbare Quellen

- Quellen mit `redistributable: false` (derzeit `PGAA-XLS`, außerdem `user` im Overlay) dürfen
  **nie** in die verteilte Datenbank (`src/nucdb/data`, Releases, NucOffice-Verteilung).
- Für den eigenen Gebrauch gibt es eine **lokale Datenbank** = verteilte Daten + nicht weitergebbare
  Quellen: `nucdb build db-local --src db-source --local`. Der Ordner `db-local/` steht in
  `.gitignore`. Tools nutzen sie, indem sie ihren Pfad ausdrücklich übergeben (Abschnitt 2, Punkt 1).
- `nucdb validate --distributable` meldet Fehler, sobald Daten aus solchen Quellen enthalten sind.
  Das ist Pflicht vor jeder Veröffentlichung; ein Test prüft es für `src/nucdb/data`.

## 5. Regeln für Konsumenten

1. Die zentrale Datenbank **nur lesen**. Eigene Einträge gehen ausschließlich in die Overlay-Datenbank (8).
2. Beim Laden die `schema_version` prüfen. Bei gleicher MAJOR-Version ist die Datenbank
   kompatibel, sonst eine verständliche Meldung ausgeben.
3. Unbekannte Dateien, Felder und Größen ignorieren.
4. **Prompt-Gammas nie mit Zerfallsstrahlung mischen.** `prompt_gamma.json` nur laden, wenn der
   Nutzer ausdrücklich ein (n,γ)-Spektrum auswertet.
5. Für die Peak-Identifikation in Zerfallsspektren `decay_gamma.json` und `special_lines.json`
   verwenden.
6. Bei der Anzeige von Werten die Quelle verfügbar machen, z. B. als Tooltip.
7. Python-Tools nutzen die Lese-API aus Abschnitt 9. Andere Sprachen lesen die Dateien direkt
   nach dieser Spezifikation.

### Peak-Identifikation (`find_gammas`)

- Durchsucht Gamma-/Röntgenlinien (bevorzugte Quelle je Nuklid), feste Sonderlinien und Single-/
  Double-Escape-Peaks. Prompt-Gammas nie.
- Standard-Sortierung nach `score` = Intensität × exp(−½·(Δ/(tol/2))²); Escape-Peaks zählen mit 5 %
  bzw. 2 %, feste Sonderlinien mit 0,5, Linien ohne Intensität mit 10⁻⁴. `sort="delta"` sortiert nur
  nach Abstand.
- 511-keV-Linien einzelner β⁺-Strahler (`ANN`) sind standardmäßig ausgeblendet; die Sonderlinie
  `annihilation` steht für alle (`include_annihilation=True` blendet sie ein).
- Die Datenbank enthält alle bekannten Nuklide, also auch sehr exotische. Tools sollten die Suche
  deshalb auf ihre Nuklidbibliothek (`nuclides=`) oder eine Mindest-Halbwertszeit beschränken.

## 6. Abgeleitete Größen

Sie werden **nicht gespeichert**, die API berechnet sie:

- `n = a − z`
- λ = ln 2 / T½
- B = Z·m(¹H) + N·m_n − M_Atom (mit der **Atommasse von ¹H**, nicht der Protonenmasse)
- Kettenrechnungen (Bateman, Gleichgewichte)

## 6a. Einheiten umrechnen, eingeben und anzeigen

**Grundsatz:** In der Datenbank steht jede Größe in genau **einer** festen Einheit (3.1),
z. B. Halbwertszeiten immer in Sekunden. Umgerechnet wird **ausschließlich im Paket `nucdb`**
(Modul `nucdb.units`). Kein Tool baut eigene Umrechnungen. Dadurch rechnen alle Tools gleich, und
Fehler müssen nur an einer Stelle behoben werden.

### Festgelegte Definitionen

| Einheit | Wert |
|---|---|
| 1 a (Jahr) | 365.2422 d = 31 556 926,08 s (tropisches Jahr, wie in NUBASE2020; NUBASE nennt gerundet 31 556 926 s). DDEP rechnet ebenso: bei 17 von 19 eindeutig entscheidbaren Nukliden passen die DDEP-Angaben in Jahren und Sekunden nur zum tropischen Jahr |
| 1 d | 86 400 s |

Importer rechnen Originalangaben mit der Jahresdefinition der jeweiligen Quelle um. Die
Originalschreibweise bleibt in `_text` erhalten.

### Unterstützte Einheiten (erweiterbar)

| Größe | Einheiten |
|---|---|
| Zeit, Halbwertszeit | `fs ps ns µs (us) ms s min h d a` (Synonyme: `y`, `yr`, `Jahr`, `Jahre`, `Tag`, `Tage`, `Std`) |
| Zerfallskonstante | `1/s 1/min 1/h 1/d 1/a` (auch `s^-1`, `s⁻¹`, `/s`) |
| Energie | `eV keV MeV` |
| Masse | `u`, `MeV/c²`, `kg` |
| Wirkungsquerschnitt | `µb mb b`, `cm²` |
| Intensität, Häufigkeit | Bruchteil, `%` |

Groß-/Kleinschreibung wird toleriert, wo das eindeutig ist. `M` (Mega) und `m` (milli) werden
dabei nicht verwechselt.

### Funktionen

```python
from nucdb import units
units.convert(3.8235, "d", "h")                      # 91.764
units.parse_quantity("5,2711(8) a", kind="time")     # Quantity(value=166339713.06…, unc=25245.5…, unit="s")
units.parse_quantity("2.1e-6 1/s", kind="half_life").value   # Zerfallskonstante als Eingabe -> T½ in s
units.half_life_to_lambda(t_s, unc_s)                # λ und Unsicherheit (fortgepflanzt)
units.format_time(166339713, unit="auto")            # "5.271 a" – sinnvolle Einheit automatisch
units.format_time(166339713, "d", 25245, decimal_comma=True)   # "1925,23(29) d"
co.half_life(unit="d")                               # Nuklid-Objekte nehmen eine Wunscheinheit an
co.decay_constant(unit="1/h")
```

- **Eingabe:** Wo Nutzer eine Halbwertszeit eintragen (Editor, Overlay, Konsumenten-GUIs), darf
  wahlweise eine Halbwertszeit **oder** eine Zerfallskonstante in jeder unterstützten Einheit
  eingegeben werden. Gespeichert wird immer `half_life_s`.
- **Anzeige:** Die Einheit ist in jedem Tool frei wählbar. `unit="auto"` wählt eine gut lesbare
  Einheit. Unsicherheiten werden immer mit umgerechnet.
- `nucdb.units` braucht wie die übrige Lese-API nur die Standardbibliothek. Eigene Umrechnungen von
  Halbwertszeiten in den Tools werden bei der Umstellung durch `nucdb.units` ersetzt
  (`NUCDB-INTEGRATION.md`).

## 7. Versionsregeln

| Änderung | Version |
|---|---|
| neue Größe in `quantities.json`, neues optionales Feld, neue Datei | MINOR |
| Feld umbenannt oder entfernt, Einheit oder Bedeutung geändert | MAJOR |
| Datenänderung | `data_version` |

## 8. Ergänzungsdatenbank (Overlay) für eigene Nutzereinträge

- Ort: `<Benutzer-Datenordner>/nucdb-user/`
  - Linux: `~/.local/share/nucdb-user/`
  - Windows: `%LOCALAPPDATA%\nucdb-user\`
- Gleiches Format wie die zentrale Datenbank, aber nur die Dateien, die man braucht.
  Die Quelle ist `user` oder eine eigene Quelle in `sources.json` des Overlays. Die Quelle `user`
  ist `redistributable: false`. In Overlay-Einträgen von `decay_modes.json` darf `mode` fehlen
  (z. B. wenn nur Tochter und Anteil bekannt sind).
- Die API legt das Overlay **über** die zentrale Datenbank:
  - neue Nuklide und Linien kommen hinzu,
  - zusätzliche Werte bekannter Nuklide werden angehängt,
  - ein Overlay-Wert mit `preferred: true` übersteuert den zentralen Wert.
- Alle Tools sehen dasselbe Overlay. Ein Nuklid, das in ActivityPartitioner angelegt wird, ist
  also auch in plotSPE sichtbar.
- Overlay-Einträge sind in der API und der Oberfläche als „eigener Eintrag“ erkennbar
  (`nuclide.user`, `value.user`, `line.user`).
- Der Editor kann Overlay-Einträge prüfen und in die zentrale Datenbank übernehmen.

**Schreiben** (nur über `db.user`, Abschnitt 9):

| Funktion | schreibt |
|---|---|
| `add_nuclide`, `remove_nuclide` | eigenes Nuklid samt Zerfallswegen (`nuclides.json`, `decay_modes.json`) |
| `add_value` | eigener Wert einer Größe, z. B. Halbwertszeit (`nuclides.json`) |
| `add_gamma`, `remove_gamma` | eigene Gamma-/Röntgenlinie (`decay_gamma.json`), z. B. ein in plotSPE gefundener Peak |
| `add_emission`, `remove_emission` | eigene Linie bzw. eigener Zweig jeder Strahlungsart (`decay_gamma/alpha/beta/electron.json`) |

Eigene Linien haben die Felder aus 4.7 plus optional `energy_kev_text` (Eingabe), `note` und
`added_at`. Sie lassen sich zu **jedem** Nuklid hinzufügen (zentral oder eigen) und erscheinen
sofort in `gammas()`, `find_gammas()` usw. Eine eigene Linie bei derselben Energie (±1 eV) wird
ersetzt; zentrale Linien lassen sich nicht löschen.

**Gleichzeitiges Schreiben:** Während eines Schreibvorgangs liegt im Overlay-Ordner die Sperrdatei
`.lock`. Ein zweites Programm wartet bis zu 10 s und meldet dann `OverlayLockedError`; eine Sperre,
die älter als 60 s ist (abgestürztes Programm), wird übernommen.

**Änderungen anderer Programme:** Ein laufendes Tool sieht Änderungen, die ein anderes Tool am
Overlay macht, erst nach `db.reload()`. `db.reload_if_changed()` prüft das billig (Zeitstempel der
Dateien) und lädt nur bei Bedarf neu – z. B. beim Fokuswechsel des Fensters aufrufen.

## 9. Python-Lese-API (Paket `nucdb`)

Die API hat keine GUI-Abhängigkeiten und kommt nur mit der Standardbibliothek aus. Dateien werden
erst beim ersten Zugriff geladen. Pro Datei gibt es einen Index nach Nuklid und Energie.

```python
from nucdb import NucDB
db = NucDB()                                   # Fundort nach Abschnitt 2, oder NucDB(path)
co = db.nuclide("60Co")                        # Nuclide(name="Co-60", z=27, a=60, isomer=0, …)
co.half_life_s, co.half_life("a"), co.decay_constant("1/h")
co.value("mass_u"); co.values("half_life_s")   # bevorzugter Wert bzw. alle Werte mit Quellen
db.gammas("Bi-214", min_intensity=0.005)       # aus decay_source
db.alphas("Po-214"); db.betas("Sr-90"); db.electrons("Cs-137")
db.find_gammas(609.3, tol_kev=1.5)             # Peak-ID: LineMatch(kind=decay|single_escape|double_escape|special, score)
db.find_gammas(1460.8, 1.0, nuclides=bibliothek)            # nur Kandidaten einer Nuklidbibliothek
db.find_gammas(1460.8, 1.0, min_half_life_s=3600)           # nur Nuklide mit T½ ≥ 1 h
db.prompt_gammas(element="Fe")                 # lädt prompt_gamma.json erst hier
db.find_prompt_gammas(2223.2, tol_kev=1.0)
db.activation_gammas(element="Al")             # NAA-Daten (nur lokale Datenbanken, sonst leer)
db.chain("Rn-222")                             # Kette mit Verzweigungen bis zu stabilen Nukliden
db.chain("Th-232", min_branching=1e-6, include_unknown=False)   # ohne extrem seltene/unbekannte Zweige
[m.effective_branching for m in db.decay_modes("Bi-212")]
db.decay_modes("Mo-99")                        # B- → Tc-99m 0.878 und B- → Tc-99 0.122 (Isomer-Fütterung)
db.isomer_feedings("Mo-99")                    # Rohdaten der Fütterung
db.source("NUBASE2020").citation
db.user.add_nuclide("Mo-99", half_life="65,94 h", decays=[("Tc-99m", 0.8773), ("Tc-99", 0.1227)])
db.user.add_value("Co-60", "half_life_s", "1925.3(3) d")   # eigener Wert, übersteuert zentral
db.user.remove_nuclide("Mo-99")
db.user.add_gamma("Bi-214", "1764.49(3) keV", intensity="15,3 %", note="eigene Messung")   # eigener Peak
db.user.remove_gamma("Bi-214", 1764.49)
db.user.add_emission("beta", "Co-60", "317.9 keV", intensity=0.9988, type="B-", mean_energy_kev=95.8)
db.user.emissions("gamma", "Bi-214")           # eigene Linien als Rohdatensätze
db.reload_if_changed()                         # Änderungen anderer Programme am Overlay übernehmen
db.location, db.data_version, db.schema_version      # welche Datenbank geladen ist
```

Weitere Funktionen: `db.nuclides(z=, a=, stable=)`, `db.has_nuclide()`, `db.element()`,
`db.elements()`, `db.sources()`, `db.quantities()`, `db.special_lines(kind)`, `db.emissions(kind, name)`,
`db.reload()`; Module `nucdb.names` (Namen lesen/normalisieren), `nucdb.units`, `nucdb.physics`
(`compton_edge`, `backscatter`, `single_escape`, `double_escape`, Konstanten).
Fehlerklassen: `UnknownNuclideError` (Unterklasse von `KeyError`), `NuclideNameError` (`ValueError`),
`units.UnitError` (`ValueError`), `IncompatibleSchemaError`, `OverlayLockedError` (Overlay gerade
gesperrt). Ungültige Eingaben beim Schreiben ins Overlay (unbekanntes Nuklid, Energie ≤ 0, Intensität
in % statt als Bruchteil …) lösen `ValueError` mit verständlicher Meldung aus.

## 10. Was Version 1.0 zusichert

Innerhalb von 1.x bleiben **unverändert**:

- Dateinamen, Formatkennungen (`nucdb/<name>`) und der Dateiaufbau (3.4),
- alle in Abschnitt 4 genannten Felder mit Name, Einheit und Bedeutung,
- die kanonischen Nuklidnamen und die Isomer-Regel (3.3),
- die Einheiten und die Jahresdefinition (3.1, 6a),
- der Fundort (2) und das Overlay (8),
- die in Abschnitt 9 genannten Funktionen, Parameter und Attribute der Lese-API.

**Hinzukommen** dürfen: neue Dateien, neue optionale Felder, neue Größen in `quantities.json`,
neue optionale Parameter, neue Funktionen, neue Quellen und neue Daten (`data_version`).
Tools müssen Unbekanntes ignorieren (Regel 5.3), dann bleiben sie mit allen 1.x-Datenbanken
lauffähig.

Nicht zugesichert sind Zahlenwerte (sie ändern sich mit neuen Evaluationen), die Reihenfolge
gleichwertiger Treffer der Peak-Suche und die Gewichte ihrer Bewertung.

## 11. Versionshistorie

| Version | Datum | Änderung |
|---|---|---|
| 0.1 | 2026-11-20 | erster Entwurf (SQLite) |
| 0.2 | 2026-11-20 | JSON statt SQLite, Fundort ohne Umgebungsvariable, `special_lines` |
| 0.3 | 2026-11-20 | Strahlungsarten in getrennten Dateien (Gamma/Alpha/Beta/Elektronen), `decay_source` je Nuklid (DDEP bevorzugt), Overlay für Nutzereinträge, `redistributable` bei Quellen, Daten CC BY 4.0, Importschwelle 0,1 % |
| 0.4 | 2026-11-20 | Abschnitt 6a: Einheiten-Umrechnung zentral in `nucdb.units`, Eingabe von T½ oder λ in beliebigen gängigen Einheiten, Jahresdefinition festgelegt |
| 0.5 | 2026-11-23 | Mit der ersten Implementierung abgeglichen: `source_priority` im Manifest und Rückfallregel für `decay_source`, Overlay-Einträge immer sichtbar, `compton_edge`, `mode` im Overlay optional, `decay_constant(unit)` als Methode, `add_value`/`remove_nuclide` |
| 0.6 | 2026-11-23 | Mit dem Import von AME2020/NUBASE2020 abgeglichen: Isomer-Regel (T½ ≥ 1 ms, Zählung m, m2 …), Zerfallsarten in NUBASE-Schreibweise, `parent_mode`/`branching_flag`/`text`, effektiver Anteil, Ketten mit `min_branching` |
| 0.7 | 2026-11-23 | Zerfallsstrahlung aus DDEP und ENSDF/LiveChart: zusätzliche Felder (`origin`, `energy_range_kev`, `beta_delayed`, `log_ft`, `ec_intensity`, `shell` …), Importschwellen im Manifest, Jahresdefinition von DDEP bestätigt |
| 0.8 | 2026-11-24 | `activation_gamma.json` (NAA), Quellenfelder je Wertgruppe in `elements.json`, lokale Datenbanken und `validate --distributable` (4.11), Größe `g_factor_westcott` |
| 1.0 | 2026-11-24 | Festgeschrieben. Neu: `isomer_feeding.json` (4.6a) mit automatischer Aufteilung der Zweige. Aufgeräumt: NAA-Felder nur in `activation_gamma.json`, Begleitfelder (`_unc`/`unc`) erklärt, Zusagen (Abschnitt 10), Verweis auf `NUCDB-INTEGRATION.md` |
| 1.1 | 2026-11-24 | Eigene Linien im Overlay schreiben (`add_gamma`, `add_emission`, `remove_*`, `emissions`), Sperre gegen gleichzeitiges Schreiben (`OverlayLockedError`), `overlay_changed()`/`reload_if_changed()`. Format unverändert, voll kompatibel zu 1.0 |
