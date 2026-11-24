"""HTML-Fassung der Dokumentation aus den Markdown-Dateien erzeugen.

    .venv/bin/python tools/build_docs.py

Quelle bleiben die Markdown-Dateien in ``docs/``; das Ergebnis landet in ``docs/html/``.
Benötigt das Paket ``markdown`` (``pip install 'nucdb[docs]'``).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "html"
PAGES = [
    ("NUCDB-SPEC.md", "spezifikation.html", "Spezifikation"),
    ("NUCDB-INTEGRATION.md", "integration.html", "Einbindung in die Tools"),
]

CSS = """
:root { --bg:#ffffff; --fg:#1d1d1f; --muted:#5f6368; --line:#d9dce1; --code:#f3f4f6; --accent:#0b57d0; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181c; --fg:#e8eaed; --muted:#9aa0a6; --line:#3c4043; --code:#23262b; --accent:#8ab4f8; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.wrap { display:flex; gap:2rem; max-width:1200px; margin:0 auto; padding:1.5rem 1rem 4rem; }
nav { flex:0 0 260px; position:sticky; top:1rem; align-self:flex-start; max-height:calc(100vh - 2rem);
      overflow:auto; font-size:.9rem; }
nav a { color:var(--muted); text-decoration:none; } nav a:hover { color:var(--accent); }
nav ul { list-style:none; padding-left:.8rem; margin:.2rem 0; } nav > ul { padding-left:0; }
nav .pages a { font-weight:600; color:var(--fg); }
main { flex:1; min-width:0; }
h1 { font-size:1.9rem; margin-top:0; } h2 { border-bottom:1px solid var(--line); padding-bottom:.3rem; margin-top:2.2rem; }
a { color:var(--accent); }
code { background:var(--code); padding:.1em .35em; border-radius:4px; font-size:.9em; }
pre { background:var(--code); padding:.9rem 1rem; border-radius:8px; overflow:auto; }
pre code { background:none; padding:0; }
table { border-collapse:collapse; display:block; overflow-x:auto; margin:1rem 0; }
th, td { border:1px solid var(--line); padding:.4rem .6rem; text-align:left; vertical-align:top; }
th { background:var(--code); }
blockquote { margin:1rem 0; padding:.6rem 1rem; border-left:4px solid var(--accent); background:var(--code); border-radius:0 6px 6px 0; }
footer { color:var(--muted); font-size:.85rem; margin-top:3rem; }
@media (max-width: 860px) { .wrap { display:block; } nav { position:static; max-height:none; margin-bottom:1.5rem; } }
"""


def render(src: Path, title: str) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-3"}})
    body = md.convert(src.read_text(encoding="utf-8"))
    # Verweise zwischen den Markdown-Dateien auf die HTML-Seiten umbiegen
    for md_name, html_name, _t in PAGES:
        body = body.replace(f"<code>{md_name}</code>", f'<a href="{html_name}"><code>{md_name}</code></a>')
    pages = "".join(f'<li><a href="{h}">{html.escape(t)}</a></li>' for _m, h, t in PAGES)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NucDB – {html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="wrap"><nav><ul class="pages">{pages}</ul><hr>{md.toc}</nav>
<main>{body}<footer>Erzeugt aus <code>docs/{src.name}</code> mit <code>tools/build_docs.py</code>.</footer></main>
</div></body></html>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for md_name, html_name, title in PAGES:
        (OUT / html_name).write_text(render(DOCS / md_name, title), encoding="utf-8", newline="\n")
        print(f"docs/html/{html_name}")
    index = re.sub(r"<title>.*?</title>", "<title>NucDB – Dokumentation</title>",
                   (OUT / PAGES[0][1]).read_text(encoding="utf-8"))
    (OUT / "index.html").write_text(index, encoding="utf-8", newline="\n")
    print("docs/html/index.html")


if __name__ == "__main__":
    main()
