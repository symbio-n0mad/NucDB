"""Kommandozeile ``nucdb``.

Beispiele::

    nucdb info
    nucdb show 60Co --unit a
    nucdb find 609.3 --tol 1.5
    nucdb find 2223.2 --prompt
    nucdb chain Rn-222
    nucdb convert "5,27 a" d
    nucdb validate [ORDNER]
    nucdb build-base ORDNER          # Pflege: Grundgerüst erzeugen/auffrischen
    nucdb manifest ORDNER            # Pflege: Prüfsummen aktualisieren
    nucdb import amdc2020 ORDNER --src db-source/amdc2020 [--download]
    nucdb build src/nucdb/data --src db-source [--download]   # alles neu aufbauen (+ curation/)
    nucdb editor                     # Editor-Oberfläche (nucdb[gui])
"""

from __future__ import annotations

import argparse
import sys

from . import SCHEMA_VERSION, __version__, units
from .db import NucDB, UnknownNuclideError
from .names import NuclideNameError


def _open(args) -> NucDB:
    return NucDB(args.db, overlay=not args.no_overlay)


def cmd_info(args) -> int:
    db = _open(args)
    print(f"Datenbank:      {db.location}")
    print(f"Schema:         {db.schema_version} (Bibliothek {SCHEMA_VERSION})")
    print(f"Datenstand:     {db.data_version}")
    print(f"Ergänzungs-DB:  {db.overlay_location or '—'}")
    print(f"Nuklide:        {len(db.nuclides())}")
    print("Quellen:")
    for s in db.sources().values():
        flag = "" if s.redistributable else "  [nicht weitergebbar]"
        print(f"  {s.key:16s} {s.citation}{flag}")
    return 0


def cmd_show(args) -> int:
    db = _open(args)
    n = db.nuclide(args.nuclide)
    print(f"{n.name}  Z={n.z} N={n.n} A={n.a}" + (f" Isomer {n.isomer}" if n.isomer else "")
          + ("  [eigener Eintrag]" if n.user else ""))
    print(f"  Halbwertszeit: {n.format_half_life(args.unit)}")
    lam = n.decay_constant()
    if lam:
        print(f"  Zerfallskonst.: {units.format_quantity(lam, args.lambda_unit, kind='decay_constant')}")
    for q in n.quantities:
        if q == "half_life_s":
            continue
        for v in n.values(q):
            mark = "*" if v.preferred else " "
            unc = f"± {v.unc:.6g}" if v.unc is not None else ""
            flag = f" ({v.flag})" if v.flag else ""
            print(f"  {mark} {q:32s} {v.value!s:>16} {unc:14s}{flag} [{v.source}]")
    for m in db.decay_modes(n.name):
        b = "?" if m.branching is None else f"{m.branching:.6g}"
        print(f"  Zerfall {m.mode or '?':6s} → {m.daughter or '—':10s} Anteil {b}  [{m.source}]")
    for kind in ("gamma", "alpha", "beta", "electron"):
        lines = db.emissions(kind, n.name, min_intensity=args.min_intensity)
        if lines:
            print(f"  {kind}:")
            for x in lines:
                it = "—" if x.intensity is None else f"{100 * x.intensity:.4g} %"
                extra = x.fields.get("radiation") or x.fields.get("type") or ""
                print(f"    {x.energy_kev:12.4f} keV  {it:>12s}  {extra}  [{x.source}]")
    return 0


def cmd_find(args) -> int:
    db = _open(args)
    if args.prompt:
        matches = db.find_prompt_gammas(args.energy, args.tol)
    else:
        matches = db.find_gammas(args.energy, args.tol, min_intensity=args.min_intensity)
    if not matches:
        print("Keine Treffer.")
        return 1
    for m in matches:
        line = m.line
        who = getattr(line, "nuclide", None) or getattr(line, "target", None) or getattr(line, "origin", None) \
            or getattr(line, "kind", "")
        it = getattr(line, "intensity", None)
        it_s = "" if it is None else f"{100 * it:.4g} %"
        print(f"{m.energy_kev:12.4f} keV  Δ={m.delta_kev:+8.3f}  {m.kind:14s} {who!s:12s} {it_s}")
    return 0


def cmd_chain(args) -> int:
    db = _open(args)
    ch = db.chain(args.nuclide)
    for name in ch.nuclides:
        n = db.nuclide(name)
        print(f"{name:12s} {n.format_half_life()}")
        for e in ch.daughters(name):
            b = "?" if e.branching is None else f"{e.branching:.6g}"
            print(f"    → {e.daughter or '(Spaltung)':12s} {e.mode or '?':6s} {b}")
    for u in ch.unknown:
        print(f"FEHLER: Tochter {u} fehlt in der Datenbank")
    for o in ch.open_ends:
        print(f"Hinweis: {o} ist instabil, Zerfall unbekannt")
    return 0


def cmd_convert(args) -> int:
    if args.to.strip().startswith(("1/", "/")) or "^-1" in args.to or "⁻¹" in args.to:
        t = units.parse_quantity(args.value, "half_life")
        lam, ulam = units.half_life_to_lambda(t.value, t.unc)
        print(units.format_quantity(lam, args.to, ulam, kind="decay_constant", digits=args.digits))
        return 0
    try:
        kind, _ = units.lookup(args.to)
    except units.UnitError as e:
        print(e, file=sys.stderr)
        return 2
    q = units.parse_quantity(args.value, "half_life" if kind == "time" else kind)
    print(units.format_quantity(q.value, args.to, q.unc, kind=kind, digits=args.digits))
    return 0


def cmd_validate(args) -> int:
    from .locate import find_database
    from .validate import validate
    root = find_database(args.path or args.db)
    issues = validate(root, overlay=args.overlay, distributable=args.distributable)
    for i in issues:
        print(i)
    errors = sum(1 for i in issues if i.level == "error")
    print(f"{root}: {errors} Fehler, {len(issues) - errors} Warnungen")
    return 1 if errors else 0


def cmd_build_base(args) -> int:
    from .maintenance import create_base
    root = create_base(args.path, data_version=args.data_version)
    print(f"Grundgerüst geschrieben: {root}")
    return 0


IMPORTERS = {"amdc2020": "nucdb.importers.amdc2020", "ddep": "nucdb.importers.ddep",
             "livechart": "nucdb.importers.livechart", "pgaa": "nucdb.importers.pgaa_xls"}


def cmd_import(args) -> int:
    import importlib
    from pathlib import Path
    from .maintenance import update_manifest
    mod = importlib.import_module(IMPORTERS[args.source])
    src = Path(args.src)
    if args.download:
        mod.fetch(src)
    res = mod.run(Path(args.path), src)
    update_manifest(args.path, data_version=args.data_version)
    print(res["summary"])
    return 0


def cmd_build(args) -> int:
    from .maintenance import build_all
    from pathlib import Path
    from .curation import default_curation_dir
    cur = Path(args.curation) if args.curation else default_curation_dir()
    build_all(args.path, args.src, data_version=args.data_version, download=args.download, local=args.local,
              curation=None if args.no_curation else cur)
    print(f"Datenbank aufgebaut: {args.path}")
    return 0


def cmd_editor(args) -> int:
    try:
        from .gui.app import main as gui_main
    except ImportError as e:  # PySide6 fehlt
        print(f"Der Editor braucht PySide6: pip install 'nucdb[gui]' ({e})", file=sys.stderr)
        return 2
    argv = ([args.db] if args.db else []) + (["--curation", args.curation] if args.curation else [])
    return gui_main(argv + (["--no-overlay"] if args.no_overlay else []))


def cmd_manifest(args) -> int:
    from .maintenance import update_manifest
    m = update_manifest(args.path, data_version=args.data_version)
    print(f"Manifest aktualisiert: {len(m['files'])} Dateien, Datenstand {m['data_version']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nucdb", description="NucDB – Nukliddatenbank")
    p.add_argument("--version", action="version", version=f"nucdb {__version__} (Schema {SCHEMA_VERSION})")
    p.add_argument("--db", help="Datenbankordner (Standard: automatisch suchen)")
    p.add_argument("--no-overlay", action="store_true", help="Ergänzungsdatenbank nicht verwenden")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Datenbank, Version und Quellen anzeigen").set_defaults(func=cmd_info)

    s = sub.add_parser("show", help="Nuklid anzeigen")
    s.add_argument("nuclide")
    s.add_argument("--unit", default="auto", help="Zeiteinheit der Halbwertszeit (Standard: auto)")
    s.add_argument("--lambda-unit", default="1/s", help="Einheit der Zerfallskonstante")
    s.add_argument("--min-intensity", type=float, default=None, help="Bruchteil, z. B. 0.01")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("find", help="Linien bei einer Energie suchen (Peak-Identifikation)")
    s.add_argument("energy", type=float, help="Energie in keV")
    s.add_argument("--tol", type=float, default=1.0, help="Toleranz in keV")
    s.add_argument("--min-intensity", type=float, default=None)
    s.add_argument("--prompt", action="store_true", help="Prompt-Gammas statt Zerfallslinien durchsuchen")
    s.set_defaults(func=cmd_find)

    s = sub.add_parser("chain", help="Zerfallskette anzeigen")
    s.add_argument("nuclide")
    s.set_defaults(func=cmd_chain)

    s = sub.add_parser("convert", help='Einheiten umrechnen, z. B. convert "5,27 a" d')
    s.add_argument("value", help='Wert mit Einheit, z. B. "3.8235 d" oder "2.1e-6 1/s"')
    s.add_argument("to", help="Zieleinheit")
    s.add_argument("--digits", type=int, default=6)
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("validate", help="Datenbank prüfen")
    s.add_argument("path", nargs="?")
    s.add_argument("--overlay", action="store_true", help="Ordner ist eine Ergänzungsdatenbank")
    s.add_argument("--distributable", action="store_true",
                   help="Fehler bei Daten aus nicht weitergebbaren Quellen (vor jeder Veröffentlichung)")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("build-base", help="(Pflege) Grundgerüst erzeugen bzw. auffrischen")
    s.add_argument("path")
    s.add_argument("--data-version")
    s.set_defaults(func=cmd_build_base)

    s = sub.add_parser("build", help="(Pflege) Datenbank vollständig aus den Rohdaten neu aufbauen")
    s.add_argument("path", help="Zielordner (wird geleert)")
    s.add_argument("--src", default="db-source", help="Ordner mit den Rohdaten-Unterordnern")
    s.add_argument("--download", action="store_true", help="fehlende Rohdaten herunterladen (LiveChart: ~1 h)")
    s.add_argument("--local", action="store_true",
                   help="auch nicht weitergebbare Quellen (PGAA-Excel) aufnehmen – nur für db-local/")
    s.add_argument("--curation", help="Kurationsordner (Standard: curation/ im Repository)")
    s.add_argument("--no-curation", action="store_true", help="Korrekturen aus dem Editor nicht anwenden")
    s.add_argument("--data-version")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("editor", help="Editor-Oberfläche starten (braucht nucdb[gui])")
    s.add_argument("--curation", help="Kurationsordner für Änderungen an der zentralen Datenbank")
    s.set_defaults(func=cmd_editor)

    s = sub.add_parser("import", help="(Pflege) Primärquelle in eine Datenbank importieren")
    s.add_argument("source", choices=sorted(IMPORTERS))
    s.add_argument("path", help="Datenbankordner")
    s.add_argument("--src", required=True, help="Ordner mit den Originaldateien der Quelle")
    s.add_argument("--download", action="store_true", help="fehlende Originaldateien herunterladen")
    s.add_argument("--data-version")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("manifest", help="(Pflege) Manifest mit Prüfsummen aktualisieren")
    s.add_argument("path")
    s.add_argument("--data-version")
    s.set_defaults(func=cmd_manifest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (UnknownNuclideError, NuclideNameError, units.UnitError, FileNotFoundError, ValueError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
