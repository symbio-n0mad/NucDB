"""Zerfallsstrahlung von der IAEA LiveChart-API holen (ENSDF-Daten), mit Zwischenspeicher.

Die API liefert pro Abfrage ein Nuklid (Z, A) und eine Strahlungsart; Isomere sind über die
Spalte ``p_energy`` (Energie des Mutterzustands) enthalten. Jede Antwort wird als Datei
``<A><symbol>_<typ>.csv`` gespeichert. Vorhandene Dateien werden nicht erneut geladen, ein
abgebrochener Lauf setzt also einfach fort.

Aufruf (Pflege)::

    python -m nucdb.importers.livechart_fetch --db src/nucdb/data --out db-source/livechart
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import elements

API = "https://nds.iaea.org/relnsd/v1/data?fields=decay_rads&nuclides={code}&rad_types={rt}"
RAD_TYPES = ("g", "x", "e", "a", "bm", "bp")
#: Welche Strahlungsarten abhängig von den Zerfallsarten abgefragt werden
_MODE_TYPES = {"A": "a", "B-": "bm", "B+": "bp", "EC": "bp", "EC+B+": "bp", "e+": "bp"}


def code(z: int, a: int) -> str:
    return f"{a}{elements.symbol(z).lower()}"


def targets_from_db(db_path: Path, min_half_life_s: float = 1.0) -> list[tuple[int, int, set[str]]]:
    """(Z, A, Strahlungsarten) für alle Massenketten mit einem Zustand mit T½ ≥ Grenze."""
    from ..db import NucDB
    db = NucDB(db_path, overlay=False)
    want: dict[tuple[int, int], set[str]] = {}
    for n in db.nuclides(stable=False):
        t = n.half_life_s
        if t is None or t < min_half_life_s or n.z == 0:
            continue
        types = want.setdefault((n.z, n.a), {"g", "x", "e"})
        for m in db.decay_modes(n.name, all_sources=True):
            rt = _MODE_TYPES.get(str(m.mode))
            if rt:
                types.add(rt)
    return sorted((z, a, t) for (z, a), t in want.items())


def fetch_one(z: int, a: int, rt: str, out: Path, *, retries: int = 3) -> Path:
    target = out / f"{code(z, a)}_{rt}.csv"
    if target.is_file():
        return target
    url = API.format(code=code(z, a), rt=rt)
    req = urllib.request.Request(url, headers={"User-Agent": "nucdb-importer"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            tmp = target.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(target)
            return target
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
            print(f"  Wiederholung {code(z, a)} {rt}: {e}", file=sys.stderr)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="Datenbank mit Nukliden (nach AME/NUBASE-Import)")
    ap.add_argument("--out", required=True, help="Zwischenspeicher für die CSV-Antworten")
    ap.add_argument("--min-half-life", type=float, default=1.0, help="Sekunden (Standard 1)")
    ap.add_argument("--delay", type=float, default=0.25, help="Pause je Verbindung zwischen Abfragen in s")
    ap.add_argument("--workers", type=int, default=3, help="gleichzeitige Verbindungen (schonend: ≤ 3)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(z, a, rt) for z, a, types in targets_from_db(Path(args.db), args.min_half_life)
            for rt in RAD_TYPES if rt in types]
    todo = [j for j in jobs if not (out / f"{code(j[0], j[1])}_{j[2]}.csv").is_file()]
    print(f"{len(jobs)} Abfragen, davon {len(todo)} noch offen", flush=True)
    failed = 0
    done = 0

    def work(job):
        z, a, rt = job
        fetch_one(z, a, rt, out)
        time.sleep(args.delay)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(work, j): j for j in todo}
        for fut in as_completed(futs):
            done += 1
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001 - weitermachen, am Ende melden
                failed += 1
                z, a, rt = futs[fut]
                print(f"FEHLER {code(z, a)} {rt}: {e}", file=sys.stderr, flush=True)
            if done % 500 == 0:
                print(f"{done}/{len(todo)}", flush=True)
    print(f"fertig, {failed} Fehler", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
