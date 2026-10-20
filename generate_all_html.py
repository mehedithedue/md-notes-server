#!/usr/bin/env python3
import argparse
import html as html_escape
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import markdown  # noqa: F401
except ImportError:
    sys.exit("markdown is not installed. Run: pip install -r requirements.txt")

# Rendering, token colours and the feature script are shared with serve.py so a
# page looks the same opened from disk, over the LAN server, or from the S3 build.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from serve import FEATURE_CSS, FEATURE_JS, render_markdown_body  # noqa: E402

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
  <title>{{TITLE}}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&amp;family=JetBrains+Mono:wght@400..500&amp;display=swap" rel="stylesheet">
  <script>
    // Initialize theme and width before first paint
    (function() {
      // Dark is the default; the OS preference does not override it.
      document.documentElement.setAttribute('data-theme', localStorage.getItem('doc-theme') || 'dark');

      const savedWidth = localStorage.getItem('doc-width') || 'wide';
      document.documentElement.setAttribute('data-width', savedWidth);
    })();
  </script>
  <style>
    :root, html[data-theme="dark"] {
      --bg: #0d1117; --bg-soft: #161b22; --bg-code: #161b22;
      --fg: #e6edf3; --fg-muted: #8b949e; --fg-strong: #f0f6fc;
      --border: #30363d; --accent: #58a6ff; --code: #79c0ff;
    }
    html[data-theme="light"] {
      --bg: #ffffff; --bg-soft: #f6f8fa; --bg-code: #f6f8fa;
      --fg: #1f2328; --fg-muted: #656d76; --fg-strong: #010409;
      --border: #d1d9e0; --accent: #0969da; --code: #0550ae;
    }

    /* Responsive width modes */
    html[data-width="normal"] { --container-max-width: 900px; }
    html[data-width="wide"]   { --container-max-width: 1250px; }
    html[data-width="full"]   { --container-max-width: 95vw; }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      padding: 0 clamp(16px, 3.5vw, 48px) 80px;
      background: var(--bg); color: var(--fg);
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 16.5px;
      line-height: 1.75;
      -webkit-font-smoothing: antialiased;
      transition: background 0.2s ease, color 0.2s ease;
    }

    .top-bar {
      width: 100%;
      max-width: var(--container-max-width, 1250px);
      margin: 0 auto;
      padding: 16px 0;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 14px;
      transition: max-width 0.2s ease;
    }
    a.back-link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 0;
    }
    a.back-link:hover { text-decoration: underline; }
    .bottom-bar {
      margin-top: 64px;
      padding-top: 24px;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 14px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .nav-btn {
      background: var(--bg-soft);
      color: var(--fg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 12px;
      min-height: 36px;
      font-size: 13px;
      cursor: pointer;
      font-family: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
      touch-action: manipulation;
    }
    .nav-btn:hover, .nav-btn:active {
      border-color: var(--accent);
      color: var(--accent);
    }

    .container {
      width: 100%;
      max-width: var(--container-max-width, 1250px);
      margin: 32px auto 0;
      transition: max-width 0.2s ease;
    }

    h1, h2, h3, h4, h5, h6 {
      color: var(--fg-strong); font-weight: 600;
      margin-top: 36px; margin-bottom: 14px; line-height: 1.3;
    }
    h1 { font-size: clamp(1.8rem, 2.5vw, 2.4rem); border-bottom: 1px solid var(--border); padding-bottom: 10px; }
    h2 { font-size: clamp(1.4rem, 2vw, 1.75rem); }
    h3 { font-size: clamp(1.15rem, 1.6vw, 1.35rem); }
    p { margin: 16px 0; }
    ul, ol { padding-left: 26px; margin: 14px 0; }
    li { margin: 8px 0; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    strong { color: var(--fg-strong); }
    hr { border: none; border-top: 1px solid var(--border); margin: 40px 0; }

    blockquote {
      margin: 20px 0;
      padding: 12px 20px;
      border-left: 4px solid var(--accent);
      background: var(--bg-soft);
      color: var(--fg-muted);
      border-radius: 0 8px 8px 0;
    }
    blockquote p { margin: 6px 0; }

    /* Tables */
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 28px 0;
      overflow-x: auto;
      display: block;
      -webkit-overflow-scrolling: touch;
    }
    th, td { border: 1px solid var(--border); padding: 12px 16px; text-align: left; font-size: 15px; }
    th { background: var(--bg-soft); font-weight: 600; color: var(--fg-strong); }
    tr:nth-child(even) { background: var(--bg-soft); }

    /* Code & Pre */
    code {
      font-family: "JetBrains Mono", Consolas, Menlo, Monaco, monospace;
      background: var(--bg-code); color: var(--code);
      padding: 3px 6px; border-radius: 6px; font-size: 0.9em;
    }
    pre, div.codehilite pre {
      background: var(--bg-code);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px 20px;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      position: relative;
      font-size: 14.5px;
      line-height: 1.6;
      margin: 24px 0;
    }
    pre code, div.codehilite pre code {
      background: transparent; padding: 0; border-radius: 0; color: inherit; font-size: inherit;
    }

    .copy-btn {
      position: absolute; top: 10px; right: 10px;
      background: var(--bg-soft); color: var(--fg-muted);
      border: 1px solid var(--border); border-radius: 5px;
      padding: 6px 12px; min-height: 32px; font-size: 12px; cursor: pointer;
      font-family: inherit; transition: all 0.15s ease;
      touch-action: manipulation;
    }
    .copy-btn:hover { color: var(--fg-strong); border-color: var(--accent); }

    img { max-width: 100%; height: auto; border-radius: 8px; }

    .mermaid {
      text-align: center;
      margin: 28px 0;
      background: var(--bg-soft);
      padding: 20px;
      border-radius: 8px;
      border: 1px solid var(--border);
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    .mermaid svg {
      max-width: 100%;
      height: auto;
      min-width: 320px;
    }
    /* mermaid's dark theme paints subgraph titles near-black on a dark fill,
       which is unreadable. Keep every diagram label at the page text colour. */
    html[data-theme="dark"] .mermaid svg text,
    html[data-theme="dark"] .mermaid svg .nodeLabel,
    html[data-theme="dark"] .mermaid svg .edgeLabel,
    html[data-theme="dark"] .mermaid svg .cluster-label,
    html[data-theme="dark"] .mermaid svg .messageText,
    html[data-theme="dark"] .mermaid svg .labelText,
    html[data-theme="dark"] .mermaid svg .loopText,
    html[data-theme="dark"] .mermaid svg .noteText,
    html[data-theme="dark"] .mermaid svg div,
    html[data-theme="dark"] .mermaid svg span {
      fill: #e6edf3 !important;
      color: #e6edf3 !important;
    }

    @media (max-width: 768px) {
      body { padding: 0 14px 60px; font-size: 16px; }
      .top-bar { padding: 12px 0; }
      .container { margin-top: 20px; }
    }
{{FEATURE_CSS}}
  </style>
</head>
<body>
  <div class="top-bar">
    <a href="{{INDEX_HREF}}" class="back-link">← Back to Index</a>
    <div class="top-actions">
      <button id="width-toggle" class="nav-btn" type="button" title="Cycle screen width: Normal / Wide / Full">↔ Width: Wide</button>
      <button id="theme-toggle" class="nav-btn" type="button" title="Toggle theme">☀️ Light Mode</button>
    </div>
  </div>
  <div class="container">
    {{CONTENT}}
    <footer class="bottom-bar">
      <a href="{{INDEX_HREF}}" class="back-link">← Back to Index</a>
      <a href="#" class="nav-btn">↑ Back to Top</a>
    </footer>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  {{FEATURE_JS}}
  <script>
    // Width switcher
    const widthBtn = document.getElementById('width-toggle');
    const widthModes = ['wide', 'full', 'normal'];
    const widthLabels = {
      'wide': '↔ Width: Wide',
      'full': '↔ Width: Full',
      'normal': '↔ Width: Normal'
    };

    function setWidth(mode) {
      document.documentElement.setAttribute('data-width', mode);
      localStorage.setItem('doc-width', mode);
      if (widthBtn) widthBtn.textContent = widthLabels[mode] || '↔ Width';
    }

    const initialWidth = localStorage.getItem('doc-width') || 'wide';
    setWidth(initialWidth);

    if (widthBtn) {
      widthBtn.onclick = function() {
        const cur = document.documentElement.getAttribute('data-width') || 'wide';
        const next = widthModes[(widthModes.indexOf(cur) + 1) % widthModes.length];
        setWidth(next);
      };
    }

    // Theme toggle
    const toggleBtn = document.getElementById('theme-toggle');
    function updateThemeBtn(theme) {
      if (toggleBtn) {
        toggleBtn.textContent = theme === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';
      }
    }
    const curTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    updateThemeBtn(curTheme);

    if (toggleBtn) {
      toggleBtn.onclick = function() {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('doc-theme', next);
        updateThemeBtn(next);
        renderMermaid(true);
      };
    }

    // Render Mermaid diagrams. The source is kept on each div because mermaid
    // bakes colours into the SVG and cannot restyle in place -- a theme change
    // has to redraw from scratch.
    function mermaidConfig() {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark';
      return {
        startOnLoad: false,
        securityLevel: 'loose',
        theme: dark ? 'dark' : 'default',
        themeVariables: dark ? {
          textColor: '#e6edf3',
          titleColor: '#e6edf3',
          nodeTextColor: '#e6edf3',
          labelColor: '#e6edf3',
          clusterBkg: '#1c2128',
          clusterBorder: '#30363d',
          lineColor: '#8b949e'
        } : {}
      };
    }

    function renderMermaid(redraw) {
      if (typeof mermaid === 'undefined') return;
      document.querySelectorAll('pre code.language-mermaid').forEach(function(el) {
        const pre = el.parentElement;
        const div = document.createElement('div');
        div.className = 'mermaid';
        div.setAttribute('data-src', el.textContent);
        div.textContent = el.textContent;
        pre.replaceWith(div);
      });
      const nodes = Array.from(document.querySelectorAll('div.mermaid[data-src]'));
      if (!nodes.length) return;
      if (redraw) {
        nodes.forEach(function(d) {
          d.removeAttribute('data-processed');
          d.textContent = d.getAttribute('data-src');
        });
      }
      mermaid.initialize(mermaidConfig());
      try { mermaid.run({ nodes: nodes }); } catch (e) {}
    }
    renderMermaid(false);

    // Add copy button to code blocks
    document.querySelectorAll('pre').forEach(function(pre) {
      if (pre.querySelector('code.language-mermaid')) return;
      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'Copy';
      btn.type = 'button';
      btn.onclick = function() {
        const code = pre.querySelector('code') ? pre.querySelector('code').innerText : pre.innerText;
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(code).then(function() {
            btn.textContent = 'Copied!';
            setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
          });
        } else {
          const ta = document.createElement('textarea');
          ta.value = code;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          try {
            document.execCommand('copy');
            btn.textContent = 'Copied!';
            setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
          } catch (e) {}
          document.body.removeChild(ta);
        }
      };
      pre.appendChild(btn);
    });
  </script>
</body>
</html>
"""


def extract_title(md_text: str, file_path: Path) -> str:
    """Extract first H1 title or fallback to clean filename."""
    for line in md_text.splitlines()[:30]:
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            title = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", title)
            title = re.sub(r"[*_`]", "", title)
            return title
    return file_path.stem.replace("_", " ").replace("-", " ").title()


def index_href(md_path: Path, base_dir: Path) -> str:
    """Link back to the single index.html at the root of the docs folder.

    With --recursive a file can sit in a subdirectory, where a bare
    "index.html" would point at a sibling that does not exist.
    """
    try:
        depth = len(md_path.resolve().relative_to(base_dir).parts) - 1
    except ValueError:
        depth = 0
    return "../" * depth + "index.html"


def convert_file(md_path: Path, base_dir: Path, force: bool = False) -> str:
    """Converts a single markdown file to HTML.
    Returns: 'converted', 'skipped', or 'error'
    """
    html_path = md_path.with_suffix(".html")
    try:
        if not force and html_path.exists():
            if html_path.stat().st_mtime >= md_path.stat().st_mtime:
                return "skipped"

        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()

        html_content = render_markdown_body(md_text)

        title = html_escape.escape(extract_title(md_text, md_path))
        final_html = (
            TEMPLATE.replace("{{TITLE}}", title)
            .replace("{{INDEX_HREF}}", index_href(md_path, base_dir))
            .replace("{{FEATURE_CSS}}", FEATURE_CSS)
            .replace("{{FEATURE_JS}}", FEATURE_JS)
            .replace("{{CONTENT}}", html_content)
        )

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(final_html)

        print(f"  [✓] {md_path.name} -> {html_path.name}")
        return "converted"
    except Exception as e:
        print(f"  [✗] Error processing {md_path.name}: {e}", file=sys.stderr)
        return "error"


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown files to beautifully styled HTML.")
    parser.add_argument("files", nargs="*", help="Specific .md file(s) to convert")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild all HTML files (ignore timestamps)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Scan subdirectories recursively")
    parser.add_argument("--index", action="store_true", help="Automatically run generate_index.py after conversion")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent

    if args.files:
        md_files = [Path(f).resolve() for f in args.files]
    else:
        ignore_dirs = {".venv", "venv", ".git", ".claude", "__pycache__", ".idea", ".vscode"}
        if args.recursive:
            md_files = [
                p for p in base_dir.rglob("*.md")
                if not any(part in ignore_dirs for part in p.parts)
            ]
        else:
            md_files = [p for p in base_dir.glob("*.md")]

    if not md_files:
        print("No .md files found.")
        return

    t0 = time.perf_counter()
    stats = {"converted": 0, "skipped": 0, "error": 0}

    print(f"Checking {len(md_files)} Markdown file(s)...")
    for path in sorted(md_files):
        res = convert_file(path, base_dir, force=args.force)
        stats[res] += 1

    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed:.2f}s: {stats['converted']} converted, {stats['skipped']} up-to-date, {stats['error']} error(s).")

    if args.index:
        index_script = base_dir / "generate_index.py"
        if index_script.exists():
            print("\nUpdating index.html...")
            subprocess.run([sys.executable, str(index_script)], cwd=str(base_dir))


if __name__ == "__main__":
    main()