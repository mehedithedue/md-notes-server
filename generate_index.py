#!/usr/bin/env python3
"""Build a static index.html listing every generated document.

This is the fallback index for browsing the folder straight off disk (or from
a plain file server). When serve.py is running it builds its own richer library
page on every request and hides this file, so you only need this if you open
the .html files directly.

    python generate_index.py
"""

import os
import sys
from pathlib import Path

TITLE = "Docs Library"

# Kept in step with serve.py: same palette, same storage key, dark by default.
IGNORE_DIRS = {".venv", "venv", ".git", ".claude", "__pycache__", ".idea", ".vscode", "scratch", "_site"}
HIDDEN = {"index.html", "sample.html"}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&amp;family=JetBrains+Mono:wght@400..500&amp;display=swap" rel="stylesheet">
<script>
  // Dark is the default; the OS preference does not override it.
  document.documentElement.setAttribute('data-theme', localStorage.getItem('doc-theme') || 'dark');
</script>
<style>
:root {{
  --bg: #0d1117; --bg-soft: #161b22; --bg-raised: #1c2128;
  --fg: #e6edf3; --fg-muted: #8b949e; --fg-strong: #f0f6fc;
  --border: #30363d; --accent: #58a6ff; --accent-soft: rgba(88,166,255,.14);
}}
html[data-theme="light"] {{
  --bg: #ffffff; --bg-soft: #f6f8fa; --bg-raised: #ffffff;
  --fg: #1f2328; --fg-muted: #656d76; --fg-strong: #010409;
  --border: #d1d9e0; --accent: #0969da; --accent-soft: rgba(9,105,218,.10);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--fg); line-height: 1.7;
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-text-size-adjust: 100%;
}}
.wrap {{ max-width: 1280px; margin: 0 auto; padding: 48px 24px 80px; }}
h1 {{ margin: 0 0 6px; font-size: 30px; font-weight: 700; color: var(--fg-strong); letter-spacing: -.02em; }}
.sub {{ color: var(--fg-muted); font-size: 14px; margin-bottom: 26px; }}
.searchbox input {{
  width: 100%; height: 46px; padding: 0 16px; border-radius: 11px; margin-bottom: 20px;
  border: 1px solid var(--border); background: var(--bg-soft); color: var(--fg);
  font: 400 15px "Inter", sans-serif; outline: none;
}}
.searchbox input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }}
.grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); }}
.card {{
  display: block; padding: 16px 18px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-soft); text-decoration: none; color: inherit; transition: .15s;
}}
.card:hover {{ border-color: var(--accent); transform: translateY(-2px); background: var(--bg-raised); }}
.card-title {{ font-weight: 600; font-size: 15.5px; color: var(--fg-strong); line-height: 1.35; }}
.card-file {{
  margin-top: 6px; font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--fg-muted); opacity: .65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.themetog {{
  position: fixed; top: 16px; right: 16px; width: 36px; height: 36px; border-radius: 9px;
  border: 1px solid var(--border); background: var(--bg-soft); color: var(--fg);
  cursor: pointer; font-size: 15px;
}}
footer {{ margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--border);
          font-size: 12.5px; color: var(--fg-muted); }}
footer code {{ font-family: "JetBrains Mono", monospace; color: var(--accent); }}
@media (max-width: 600px) {{ .wrap {{ padding: 32px 16px 60px; }} h1 {{ font-size: 24px; }} }}
@media (prefers-reduced-motion: reduce) {{ .card {{ transition: none; }} }}
</style>
</head>
<body>
<button class="themetog" title="Toggle theme">&#9680;</button>
<div class="wrap">
  <h1>{title}</h1>
  <div class="sub"><b>{count}</b> documents</div>
  <div class="searchbox"><input id="q" type="search" placeholder="Filter by name..." autocomplete="off" autofocus></div>
  <div class="grid" id="grid">
{cards}
  </div>
  <footer>
    Static index &mdash; re-run <code>generate_index.py</code> after adding files.
    Run <code>serve.py</code> instead for live search and markdown rendering.
  </footer>
</div>
<script>
  var q = document.getElementById('q');
  var cards = [].slice.call(document.getElementById('grid').children);
  q.addEventListener('input', function () {{
    var term = q.value.trim().toLowerCase();
    cards.forEach(function (c) {{ c.hidden = term && c.dataset.name.indexOf(term) < 0; }});
  }});
  document.querySelector('.themetog').addEventListener('click', function () {{
    var t = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('doc-theme', t);
    localStorage.setItem('docs-theme', t);
  }});
</script>
</body>
</html>
"""


def find_docs(base_dir: Path):
    """Every generated .html worth listing, relative to base_dir, sorted."""
    found = []
    for dirpath, dirnames, filenames in os.walk(base_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in IGNORE_DIRS]
        for name in filenames:
            if not name.endswith(".html") or name in HIDDEN or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), base_dir)
            found.append(rel.replace(os.sep, "/"))
    def created(rel):
        st = os.stat(os.path.join(base_dir, rel))
        return getattr(st, "st_birthtime", st.st_mtime)
    return sorted(found, key=created, reverse=True)  # newest created first


def generate_index():
    # Anchored to the script, not the shell's cwd, so it behaves the same
    # however it is invoked (including from generate_all_html.py --index).
    base_dir = Path(__file__).resolve().parent
    files = find_docs(base_dir)

    if not files:
        print("No .html files found. Run generate_all_html.py first.")
        return 1

    cards = []
    for rel in files:
        name = os.path.splitext(os.path.basename(rel))[0].replace("_", " ").replace("-", " ").title()
        cards.append(
            '    <a class="card" href="{href}" data-name="{search}">'
            '<div class="card-title">{name}</div>'
            '<div class="card-file">{rel}</div></a>'.format(
                href=rel, search=(name + " " + rel).lower(), name=name, rel=rel
            )
        )

    out = base_dir / "index.html"
    out.write_text(
        PAGE.format(title=TITLE, count=len(files), cards="\n".join(cards)),
        encoding="utf-8",
    )
    print("Generated %s with %d document(s)." % (out.name, len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(generate_index())
