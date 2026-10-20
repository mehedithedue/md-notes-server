#!/usr/bin/env python3
"""
Local-network docs server for this folder.

Serves the pre-generated .html files AND renders any .md file live, so you can
read everything from a tablet or phone on the same Wi-Fi.

    python serve.py                # http://<your-lan-ip>:8000
    python serve.py --port 9000
    python serve.py --no-qr
    python serve.py --no-reload    # drop the auto-refresh watcher

The index page is built on every request, so new files show up on refresh --
no need to re-run generate_index.py. Any .md is converted on request, so
editing a .md and refreshing shows the change immediately (unlike
generate_all_html.py, which skips files that already have an .html).

Every page also holds a server-sent-events stream open against /__api/watch,
so saving a file on this Mac reloads it on the tablet with no refresh at all.

Rendering matches Markdown Viewer's preview as closely as a static page can:
GitHub-flavoured Markdown (tables, task lists, ~~strikethrough~~, autolinks,
:emoji:, footnotes, definition lists, two-space nested lists), YAML front
matter as a table, > [!NOTE]-style alerts, highlight.js code colouring with a
language label and copy button on every block, Mermaid, PlantUML / D2 /
Graphviz / Vega-Lite / WaveDrom fences via kroki.io, and LaTeX math via
MathJax. The same renderer and page features are used by generate_all_html.py
and build_site.py, so the static copies look identical.

Dependencies:  .venv/bin/pip install -r requirements.txt
Offline LAN:   python serve.py --fetch-assets   (fonts, mermaid, highlight.js;
               Kroki diagrams and MathJax still need internet)
"""

import argparse
import html as html_escape
import io
import json
import os
import posixpath
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    import markdown
except ImportError:
    sys.exit("markdown is not installed. Run: .venv/bin/pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.abspath(__file__))

# Files that are machinery, not documents.
HIDDEN = {"index.html", "sample.html"}



# --------------------------------------------------------------------------
# Shared look & feel
# --------------------------------------------------------------------------

THEME_CSS = """
:root {
  --bg: #0d1117; --bg-soft: #161b22; --bg-raised: #1c2128;
  --fg: #e6edf3; --fg-muted: #8b949e; --fg-strong: #f0f6fc;
  --border: #30363d; --accent: #58a6ff; --accent-soft: rgba(88,166,255,.14);
  --code: #79c0ff; --mark: #bb8009;
}
html[data-theme="light"] {
  --bg: #ffffff; --bg-soft: #f6f8fa; --bg-raised: #ffffff;
  --fg: #1f2328; --fg-muted: #656d76; --fg-strong: #010409;
  --border: #d1d9e0; --accent: #0969da; --accent-soft: rgba(9,105,218,.10);
  --code: #0550ae; --mark: #fff8c5;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.7; -webkit-text-size-adjust: 100%;
}
::selection { background: var(--accent-soft); }
/* Transient status pill, used by the live-reload watcher. */
.docs-toast {
  position: fixed; bottom: 18px; left: 50%; transform: translate(-50%, 18px);
  padding: 8px 15px; border-radius: 999px; z-index: 1001; pointer-events: none;
  background: var(--bg-raised); border: 1px solid var(--accent); color: var(--accent);
  font: 500 12.5px/1 "Inter", sans-serif; opacity: 0;
  transition: opacity .18s ease, transform .18s ease;
}
.docs-toast.show { opacity: 1; transform: translate(-50%, 0); }
"""

ASSETS_DIR = os.path.join(ROOT, "assets")
FONTS_CSS = os.path.join(ASSETS_DIR, "fonts.css")
MERMAID_JS = os.path.join(ASSETS_DIR, "mermaid.min.js")

# Inter and JetBrains Mono are both variable fonts, so wght@300..700 asks for
# one file per subset covering the whole range rather than one file per weight.
GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Inter:wght@300..700"
    "&family=JetBrains+Mono:wght@400..500"
    "&display=swap"
)
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"

# Syntax highlighting: the same highlight.js build Markdown Viewer uses, with
# its GitHub colour palette (below) instead of a stock highlight.js theme, so
# code blocks keep this site's backgrounds and only the tokens get colour.
HLJS_JS = os.path.join(ASSETS_DIR, "highlight.min.js")
HLJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"

HLJS_CSS = """
/* highlight.js tokens -- GitHub palette, dark first, light below */
.hljs { background: transparent; }
.hljs-doctag, .hljs-keyword, .hljs-template-tag, .hljs-template-variable, .hljs-type, .hljs-variable.language_ { color: #ff7b72; }
.hljs-title, .hljs-title.class_, .hljs-title.class_.inherited__, .hljs-title.function_ { color: #d2a8ff; }
.hljs-attr, .hljs-attribute, .hljs-literal, .hljs-meta, .hljs-number, .hljs-operator, .hljs-variable, .hljs-selector-attr, .hljs-selector-class, .hljs-selector-id { color: #79c0ff; }
.hljs-regexp, .hljs-string, .hljs-meta .hljs-string { color: #a5d6ff; }
.hljs-built_in, .hljs-symbol { color: #ffa657; }
.hljs-comment, .hljs-code, .hljs-formula { color: #8b949e; }
.hljs-name, .hljs-quote, .hljs-selector-tag, .hljs-selector-pseudo { color: #7ee787; }
.hljs-subst { color: #c9d1d9; }
.hljs-section { color: #1f6feb; font-weight: bold; }
.hljs-bullet { color: #79c0ff; }
.hljs-emphasis { font-style: italic; }
.hljs-strong { font-weight: bold; }
.hljs-addition { color: #aff5b4; background-color: #033a16; }
.hljs-deletion { color: #ffdcd7; background-color: #67060c; }
html[data-theme="light"] .hljs-doctag, html[data-theme="light"] .hljs-keyword, html[data-theme="light"] .hljs-template-tag, html[data-theme="light"] .hljs-template-variable, html[data-theme="light"] .hljs-type, html[data-theme="light"] .hljs-variable.language_ { color: #d73a49; }
html[data-theme="light"] .hljs-title, html[data-theme="light"] .hljs-title.class_, html[data-theme="light"] .hljs-title.class_.inherited__, html[data-theme="light"] .hljs-title.function_ { color: #6f42c1; }
html[data-theme="light"] .hljs-attr, html[data-theme="light"] .hljs-attribute, html[data-theme="light"] .hljs-literal, html[data-theme="light"] .hljs-meta, html[data-theme="light"] .hljs-number, html[data-theme="light"] .hljs-operator, html[data-theme="light"] .hljs-variable, html[data-theme="light"] .hljs-selector-attr, html[data-theme="light"] .hljs-selector-class, html[data-theme="light"] .hljs-selector-id { color: #005cc5; }
html[data-theme="light"] .hljs-regexp, html[data-theme="light"] .hljs-string, html[data-theme="light"] .hljs-meta .hljs-string { color: #032f62; }
html[data-theme="light"] .hljs-built_in, html[data-theme="light"] .hljs-symbol { color: #e36209; }
html[data-theme="light"] .hljs-comment, html[data-theme="light"] .hljs-code, html[data-theme="light"] .hljs-formula { color: #6a737d; }
html[data-theme="light"] .hljs-name, html[data-theme="light"] .hljs-quote, html[data-theme="light"] .hljs-selector-tag, html[data-theme="light"] .hljs-selector-pseudo { color: #22863a; }
html[data-theme="light"] .hljs-subst { color: #24292e; }
html[data-theme="light"] .hljs-section { color: #005cc5; }
html[data-theme="light"] .hljs-bullet { color: #005cc5; }
html[data-theme="light"] .hljs-addition { color: #22863a; background-color: #f0fff4; }
html[data-theme="light"] .hljs-deletion { color: #b31d28; background-color: #ffeef0; }
"""

# Everything below mirrors what Markdown Viewer's preview adds on top of plain
# Markdown: GitHub alerts, task lists, a front matter table, a language label
# on code blocks, math, and Kroki-rendered diagram fences. FEATURE_CSS and
# FEATURE_JS are shared by serve.py (live pages and pre-generated .html),
# build_site.py (the S3 build) and generate_all_html.py (standalone files), so
# a document looks the same whichever way it is opened.
FEATURE_CSS = HLJS_CSS + """
/* Code block header: language label + copy button, like Markdown Viewer */
.docs-pre-wrap { position: relative; margin: 22px 0; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--bg-soft); }
.docs-pre-wrap > pre { margin: 0 !important; border: 0 !important; border-radius: 0 !important; }
.docs-code-head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 30px;
  padding: 2px 6px 2px 12px; border-bottom: 1px solid var(--border);
  background: var(--bg-raised, var(--bg-soft)); color: var(--fg-muted);
}
.docs-code-lang {
  font: 600 10.5px/1 "JetBrains Mono", Consolas, monospace; letter-spacing: .06em; text-transform: uppercase;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.docs-code-head .docs-copy { position: static; opacity: 1; height: 24px; }
.docs-code-cite {
  margin-left: 10px; font-weight: 400; letter-spacing: 0; text-transform: none; opacity: .85;
}
/* generate_all_html.py's own hover button is replaced by the header button above */
.docs-pre-wrap .copy-btn, .docs-pre-wrap + .copy-btn { display: none !important; }
html[data-theme="light"] .docs-pre-wrap { background: #f6f8fa; border-color: #d1d9e0; }
html[data-theme="light"] .docs-code-head { background: #eef1f4; border-color: #d1d9e0; }
/* Task lists */
li.task-list-item { list-style: none; margin-left: -1.3em; }
li.task-list-item input[type="checkbox"] { -webkit-appearance: checkbox; appearance: checkbox; width: 14px; height: 14px; margin: 0 .5em .2em 0; vertical-align: middle; accent-color: var(--accent); color-scheme: light dark; }
dl dt { font-weight: 600; font-style: italic; margin-top: 12px; }
dl dd { margin: 4px 0 0 1.5em; }
/* GitHub alerts (> [!NOTE] etc.) */
.markdown-alert { padding: .6rem 1rem; margin: 18px 0; border-left: .25em solid; border-radius: 6px; background: var(--bg-soft); color: var(--fg); }
.markdown-alert > :last-child { margin-bottom: 0; }
.markdown-alert > p { color: var(--fg); margin: 8px 0; }
.markdown-alert-title { margin: 0 0 6px !important; font-weight: 600; line-height: 1.25; display: flex; align-items: center; gap: 8px; }
.markdown-alert-icon { display: inline-flex; width: 16px; height: 16px; }
.markdown-alert-icon svg { width: 16px; height: 16px; fill: currentColor; }
.markdown-alert-note      { color: #4493f8; border-left-color: #4493f8; background: rgba(31, 111, 235, .15); }
.markdown-alert-tip       { color: #3fb950; border-left-color: #3fb950; background: rgba(35, 134, 54, .15); }
.markdown-alert-important { color: #ab7df8; border-left-color: #ab7df8; background: rgba(137, 87, 229, .15); }
.markdown-alert-warning   { color: #d29922; border-left-color: #d29922; background: rgba(210, 153, 34, .18); }
.markdown-alert-caution   { color: #f85149; border-left-color: #f85149; background: rgba(248, 81, 73, .18); }
html[data-theme="light"] .markdown-alert > p { color: #24292e !important; }
html[data-theme="light"] .markdown-alert-note      { color: #0969da; border-left-color: #0969da; background: #ddf4ff; }
html[data-theme="light"] .markdown-alert-tip       { color: #1a7f37; border-left-color: #1a7f37; background: #dafbe1; }
html[data-theme="light"] .markdown-alert-important { color: #8250df; border-left-color: #8250df; background: #fbefff; }
html[data-theme="light"] .markdown-alert-warning   { color: #9a6700; border-left-color: #9a6700; background: #fff8c5; }
html[data-theme="light"] .markdown-alert-caution   { color: #cf222e; border-left-color: #cf222e; background: #ffebe9; }
/* Front matter table */
.frontmatter-table { width: 100%; border-collapse: collapse; margin: 0 0 24px; font-size: 14px; }
.frontmatter-table th, .frontmatter-table td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
.frontmatter-table th { font-weight: 600; background: var(--bg-soft); width: 150px; color: var(--fg-strong); }
.frontmatter-tag { display: inline-block; margin: 2px 6px 2px 0; padding: 1px 8px; border-radius: 999px; background: var(--accent-soft, rgba(88,166,255,.14)); color: var(--accent); font-size: 12.5px; }
/* Math */
.arithmatex { overflow-x: auto; }
div.arithmatex { margin: 1em 0; text-align: center; }
mjx-container[display="true"] { margin: .6em 0 !important; }
/* Kroki diagrams (PlantUML, D2, Graphviz, Vega-Lite, WaveDrom) */
.docs-diagram { margin: 24px 0; padding: 16px; text-align: center; background: #fff; border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
.docs-diagram svg { max-width: 100%; height: auto; }
.docs-diagram.is-loading { color: var(--fg-muted); font-size: 13px; background: var(--bg-soft); }
.docs-diagram.is-failed { background: var(--bg-soft); text-align: left; padding: 0; }
.docs-diagram.is-failed pre { margin: 0; border: 0; }
.docs-diagram-note { padding: 8px 12px; font-size: 12.5px; color: #d29922; border-top: 1px solid var(--border); }
/* Keyboard keys and marks, as GitHub renders them */
kbd { display: inline-block; padding: 2px 6px; font: 11px/1.3 "JetBrains Mono", monospace; color: var(--fg); background: var(--bg-soft); border: 1px solid var(--border); border-bottom-width: 3px; border-radius: 6px; }
mark { background: var(--mark, #bb8009); color: inherit; padding: 0 2px; border-radius: 3px; }
"""

FEATURE_JS = r"""
<script>
(function () {
  if (window.__docsFeatures) return;
  window.__docsFeatures = true;

  var HLJS_SRC = window.__DOCS_HLJS_SRC || 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js';
  var MATHJAX_SRC = 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js';
  var KROKI = 'https://kroki.io';
  var DIAGRAM_FENCES = { plantuml: 'plantuml', d2: 'd2', graphviz: 'graphviz', dot: 'graphviz',
                         'vega-lite': 'vegalite', vegalite: 'vegalite', wavedrom: 'wavedrom' };
  var LANG_NAMES = { js: 'JavaScript', javascript: 'JavaScript', ts: 'TypeScript', typescript: 'TypeScript',
                     py: 'Python', python: 'Python', php: 'PHP', sh: 'Shell', bash: 'Bash', zsh: 'Shell', shell: 'Shell',
                     json: 'JSON', yaml: 'YAML', yml: 'YAML', sql: 'SQL', html: 'HTML', xml: 'XML', css: 'CSS',
                     md: 'Markdown', markdown: 'Markdown', txt: 'Text', text: 'Text', plaintext: 'Text', diff: 'Diff',
                     ini: 'INI', toml: 'TOML', env: 'Env', dockerfile: 'Dockerfile', makefile: 'Makefile', go: 'Go',
                     rb: 'Ruby', ruby: 'Ruby', java: 'Java', kotlin: 'Kotlin', swift: 'Swift', c: 'C', cpp: 'C++',
                     cs: 'C#', rs: 'Rust', rust: 'Rust', http: 'HTTP', graphql: 'GraphQL', nginx: 'Nginx', vue: 'Vue' };

  function langOf(code) {
    var m = (code.className || '').match(/\blanguage-([\w+#.-]+)/);
    return m ? m[1].toLowerCase() : '';
  }
  function isDiagram(code) {
    var l = langOf(code);
    return l === 'mermaid' || DIAGRAM_FENCES.hasOwnProperty(l);
  }
  function copyText(text, done) {
    // navigator.clipboard needs HTTPS or localhost; over LAN HTTP it is undefined.
    if (navigator.clipboard && isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
    } else {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = 0;
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  // --- GitHub alerts: > [!NOTE] / TIP / IMPORTANT / WARNING / CAUTION ---
  var ALERTS = {
    note: ['Note', 'M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM6.5 7.75A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75ZM8 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z'],
    tip: ['Tip', 'M8 1.5c-2.363 0-4 1.69-4 3.75 0 .984.424 1.625.984 2.304l.214.253c.223.264.47.556.673.848.284.411.537.896.621 1.49a.75.75 0 0 1-1.484.211c-.04-.282-.163-.547-.37-.847a8.456 8.456 0 0 0-.542-.68c-.084-.1-.173-.205-.268-.32C3.201 7.75 2.5 6.766 2.5 5.25 2.5 2.31 4.863 0 8 0s5.5 2.31 5.5 5.25c0 1.516-.701 2.5-1.328 3.259-.095.115-.184.22-.268.319-.207.245-.383.453-.541.681-.208.3-.33.565-.37.847a.751.751 0 0 1-1.485-.212c.084-.593.337-1.078.621-1.489.203-.292.45-.584.673-.848.075-.088.147-.173.213-.253.561-.679.985-1.32.985-2.304 0-2.06-1.637-3.75-4-3.75ZM5.75 12h4.5a.75.75 0 0 1 0 1.5h-4.5a.75.75 0 0 1 0-1.5ZM6 15.25a.75.75 0 0 1 .75-.75h2.5a.75.75 0 0 1 0 1.5h-2.5a.75.75 0 0 1-.75-.75Z'],
    important: ['Important', 'M0 1.75C0 .784.784 0 1.75 0h12.5C15.216 0 16 .784 16 1.75v9.5A1.75 1.75 0 0 1 14.25 13H8.06l-2.573 2.573A1.458 1.458 0 0 1 3 14.543V13H1.75A1.75 1.75 0 0 1 0 11.25Zm1.75-.25a.25.25 0 0 0-.25.25v9.5c0 .138.112.25.25.25h2a.75.75 0 0 1 .75.75v2.19l2.72-2.72a.749.749 0 0 1 .53-.22h6.5a.25.25 0 0 0 .25-.25v-9.5a.25.25 0 0 0-.25-.25Zm7 2.25v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 9a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z'],
    warning: ['Warning', 'M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z'],
    caution: ['Caution', 'M4.47.22A.749.749 0 0 1 5 0h6c.199 0 .389.079.53.22l4.25 4.25c.141.14.22.331.22.53v6a.749.749 0 0 1-.22.53l-4.25 4.25A.749.749 0 0 1 11 16H5a.749.749 0 0 1-.53-.22L.22 11.53A.749.749 0 0 1 0 11V5c0-.199.079-.389.22-.53Zm.84 1.28L1.5 5.31v5.38l3.81 3.81h5.38l3.81-3.81V5.31L10.69 1.5ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z']
  };
  [].slice.call(document.querySelectorAll('blockquote')).forEach(function (bq) {
    if (bq.classList.contains('markdown-alert')) return;
    var p = null;
    for (var i = 0; i < bq.children.length; i++) { if (bq.children[i].tagName === 'P') { p = bq.children[i]; break; } }
    if (!p) return;
    var m = p.innerHTML.match(/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:(?:\s|&nbsp;|<br\s*\/?>)+|$)/i);
    if (!m) return;
    var type = m[1].toLowerCase();
    bq.classList.add('markdown-alert', 'markdown-alert-' + type);
    p.innerHTML = p.innerHTML.slice(m[0].length);
    if (!p.textContent.trim()) p.parentNode.removeChild(p);
    var title = document.createElement('p');
    title.className = 'markdown-alert-title';
    title.innerHTML = '<span class="markdown-alert-icon" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="' +
      ALERTS[type][1] + '"></path></svg></span><span>' + ALERTS[type][0] + '</span>';
    bq.insertBefore(title, bq.firstChild);
  });

  // --- Task lists written as "- [ ]" / "- [x]" in pages generated before the
  //     tasklist extension was enabled ---
  [].slice.call(document.querySelectorAll('li')).forEach(function (li) {
    var first = li.firstChild;
    if (!first || first.nodeType !== 3) return;
    var m = first.nodeValue.match(/^\s*\[([ xX])\]\s+/);
    if (!m) return;
    first.nodeValue = first.nodeValue.slice(m[0].length);
    var box = document.createElement('input');
    box.type = 'checkbox'; box.disabled = true; box.checked = m[1] !== ' ';
    li.insertBefore(box, first);
    li.classList.add('task-list-item');
    li.parentNode.classList.add('task-list');
  });

  // --- Code blocks: header with language label + copy button ---
  [].slice.call(document.querySelectorAll('pre')).forEach(function (pre) {
    var code = pre.querySelector('code');
    if (pre.classList.contains('mermaid') || (code && isDiagram(code))) return;
    if (pre.parentNode && pre.parentNode.classList && pre.parentNode.classList.contains('docs-pre-wrap')) return;
    var wrap = document.createElement('div');
    wrap.className = 'docs-pre-wrap';
    pre.parentNode.insertBefore(wrap, pre);
    var head = document.createElement('div');
    head.className = 'docs-code-head';
    var lang = code ? langOf(code) : '';
    var label = document.createElement('span');
    label.className = 'docs-code-lang';
    label.textContent = lang ? (LANG_NAMES[lang] || lang) : 'Text';
    var btn = document.createElement('button');
    btn.className = 'docs-copy'; btn.type = 'button'; btn.textContent = 'Copy';
    btn.addEventListener('click', function () {
      copyText(pre.innerText, function () {
        btn.textContent = 'Copied'; btn.classList.add('done');
        setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1400);
      });
    });
    var cite = code && code.getAttribute('data-cite');
    if (cite) {
      var where = document.createElement('span');
      where.className = 'docs-code-cite'; where.textContent = cite; where.title = cite;
      label.appendChild(where);
    }
    head.appendChild(label); head.appendChild(btn);
    wrap.appendChild(head); wrap.appendChild(pre);
  });

  // --- highlight.js, the same build Markdown Viewer uses ---
  // Tagged blocks are highlighted directly. Untagged blocks are auto-detected
  // and only coloured when the guess is confident, so plain text stays plain.
  // Theme changes need no redraw: the palette keys every colour off
  // html[data-theme].
  function highlightCode() {
    if (typeof hljs === 'undefined') return;
    try { hljs.configure({ ignoreUnescapedHTML: true }); } catch (e) {}
    [].slice.call(document.querySelectorAll('pre code')).forEach(function (el) {
      if (el.classList.contains('hljs') || isDiagram(el)) return;
      var lang = langOf(el);
      try {
        if (lang && hljs.getLanguage(lang)) {
          hljs.highlightElement(el);
        } else if (!lang) {
          var guess = hljs.highlightAuto(el.textContent);
          if (guess.relevance >= 5) {
            el.innerHTML = guess.value; el.classList.add('hljs');
            var wrap = el.parentNode && el.parentNode.parentNode;
            var label = wrap && wrap.querySelector ? wrap.querySelector('.docs-code-lang') : null;
            if (label && guess.language) label.textContent = LANG_NAMES[guess.language] || guess.language;
          }
        }
      } catch (e) {}
    });
  }
  if (document.querySelector('pre code')) {
    if (typeof hljs !== 'undefined') {
      highlightCode();
    } else {
      var hs = document.createElement('script');
      hs.src = HLJS_SRC; hs.onload = highlightCode;
      document.head.appendChild(hs);
    }
  }

  // --- Diagram fences rendered by kroki.io (the source is sent to that
  //     service, exactly as Markdown Viewer does for these fences) ---
  var krokiBlocks = [];
  [].slice.call(document.querySelectorAll('pre code')).forEach(function (code) {
    var type = DIAGRAM_FENCES[langOf(code)];
    if (type) krokiBlocks.push([code, type]);
  });
  krokiBlocks.forEach(function (pair) {
    var code = pair[0], type = pair[1], pre = code.parentElement;
    var box = document.createElement('div');
    box.className = 'docs-diagram is-loading';
    box.setAttribute('data-kind', type);
    box.textContent = 'Rendering ' + type + ' diagram\u2026';
    pre.parentNode.replaceChild(box, pre);
    fetch(KROKI + '/' + type + '/svg', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: code.textContent })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (svg) { box.innerHTML = svg; box.classList.remove('is-loading'); })
      .catch(function (e) {
        box.classList.remove('is-loading'); box.classList.add('is-failed');
        box.innerHTML = ''; box.appendChild(pre);
        var note = document.createElement('div');
        note.className = 'docs-diagram-note';
        note.textContent = type + ' diagram could not be rendered via kroki.io (' + e.message + ').';
        box.appendChild(note);
      });
  });

  // --- Math: MathJax, loaded only when the page has any ---
  var hasMath = document.querySelector('.arithmatex') || /\$\$[\s\S]+?\$\$/.test(document.body.textContent);
  if (hasMath && typeof MathJax === 'undefined') {
    window.MathJax = {
      tex: { inlineMath: [['\\(', '\\)'], ['$', '$']], displayMath: [['\\[', '\\]'], ['$$', '$$']], processEscapes: true,
             packages: { '[+]': ['ams', 'boldsymbol'] } },
      loader: { load: ['[tex]/ams', '[tex]/boldsymbol'] },
      options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'], ignoreHtmlClass: 'docs-bar|docs-toc|docs-code-head' }
    };
    var ms = document.createElement('script');
    ms.src = MATHJAX_SRC; ms.async = true;
    document.head.appendChild(ms);
  }
})();
</script>
"""


# --------------------------------------------------------------------------
# Markdown -> HTML, shared by the live server, generate_all_html.py and
# build_site.py so every path renders the same syntax.
# --------------------------------------------------------------------------

# GitHub-flavoured extras come from pymdown-extensions (strikethrough, task
# lists, auto-links, emoji shortcodes, math, ==mark==, ^sup^). Without it the
# renderer still works, just with plain Python-Markdown's syntax.
try:
    import pymdownx.emoji  # noqa: F401
    HAVE_PYMDOWNX = True
except ImportError:
    HAVE_PYMDOWNX = False

try:
    import yaml  # PyYAML, for front matter
except ImportError:
    yaml = None

_BASE_EXTENSIONS = ["abbr", "attr_list", "def_list", "footnotes", "md_in_html", "tables",
                    "toc", "sane_lists", "admonition"]
if HAVE_PYMDOWNX:
    MD_EXTENSIONS = _BASE_EXTENSIONS + [
        "pymdownx.superfences", "pymdownx.tilde", "pymdownx.tasklist", "pymdownx.magiclink",
        "pymdownx.betterem", "pymdownx.mark", "pymdownx.caret", "pymdownx.emoji", "pymdownx.arithmatex",
    ]
    MD_EXTENSION_CONFIGS = {
        "pymdownx.arithmatex": {"generic": True},
        "pymdownx.emoji": {"emoji_index": pymdownx.emoji.gemoji, "emoji_generator": pymdownx.emoji.to_alt},
        "pymdownx.tasklist": {"custom_checkbox": False},
        "pymdownx.tilde": {"subscript": False},
    }
else:
    MD_EXTENSIONS = _BASE_EXTENSIONS + ["fenced_code"]
    MD_EXTENSION_CONFIGS = {}

_FRONT_MATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)
_MATH_FENCE_RE = re.compile(r"^```math[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)
_INLINE_DISPLAY_MATH_RE = re.compile(r"(?<!\$)\$\$([^\n$]+?)\$\$(?!\$)")
# Cursor / Claude Code citation fences: ```60:73:path/to/File.php
# superfences rejects that info string, so the block fell through as a
# paragraph and arithmatex turned every `$var` into math.
_CITE_FENCE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*(\d+):(\d+):(\S+)[ \t]*$", re.M)
_CITE_LANGS = {
    "php": "php", "py": "python", "js": "javascript", "mjs": "javascript", "ts": "typescript",
    "tsx": "tsx", "jsx": "jsx", "json": "json", "sql": "sql", "md": "markdown", "sh": "bash",
    "bash": "bash", "zsh": "bash", "yml": "yaml", "yaml": "yaml", "html": "html", "htm": "html",
    "css": "css", "scss": "scss", "xml": "xml", "vue": "vue", "blade.php": "php", "env": "ini",
    "ini": "ini", "toml": "toml", "txt": "text", "go": "go", "rs": "rust", "rb": "ruby",
    "java": "java", "kt": "kotlin", "swift": "swift", "c": "c", "h": "c", "cpp": "cpp",
}


def _cite_fence(m):
    indent, fence, start, end, path = m.groups()
    name = path.rsplit("/", 1)[-1].lower()
    ext = name.split(".", 1)[1] if "." in name else ""
    lang = _CITE_LANGS.get(ext) or _CITE_LANGS.get(ext.rsplit(".", 1)[-1], "text")
    lines = "line %s" % start if start == end else "lines %s\u2013%s" % (start, end)
    cite = "%s \u00b7 %s" % (path, lines)
    return '%s%s{.%s data-cite="%s"}' % (indent, fence, lang, cite.replace('"', "&quot;"))



def split_front_matter(text):
    """Return (data, body). data is a dict or None; mirrors Markdown Viewer's checks."""
    if not text.startswith("---"):
        return None, text
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    raw = m.group(1).strip()
    if not raw or not re.search(r"^[A-Za-z0-9_-]+\s*:", raw, re.M):
        return None, text
    if re.search(r"^#|^\s*\||^\s*```|^\s*[-*+]\s+\[", raw, re.M):
        return None, text
    data = None
    if yaml is not None:
        try:
            data = yaml.safe_load(raw)
        except Exception:
            data = None
    if data is None:
        data = {}
        for line in raw.splitlines():
            k, sep, v = line.partition(":")
            if sep and re.match(r"^[A-Za-z0-9_-]+$", k.strip()):
                data[k.strip()] = v.strip()
    if not isinstance(data, dict) or not data:
        return None, text
    return data, text[m.end():]


def _front_matter_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        if all(not isinstance(v, (dict, list, tuple)) for v in value):
            return "".join('<span class="frontmatter-tag">%s</span>' % html_escape.escape(str(v)) for v in value)
        return "<code>%s</code>" % html_escape.escape(json.dumps(value, ensure_ascii=False, default=str))
    if isinstance(value, dict):
        return "<code>%s</code>" % html_escape.escape(json.dumps(value, ensure_ascii=False, default=str))
    return html_escape.escape(str(value))


def render_front_matter(data):
    rows = "".join("<tr><th>%s</th><td>%s</td></tr>" % (html_escape.escape(str(k)), _front_matter_value(v))
                   for k, v in data.items())
    return '<table class="frontmatter-table"><tbody>%s</tbody></table>\n' % rows


_LIST_ITEM_RE = re.compile(r"^( *)([-*+]|\d+[.)])( +)(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _normalize_gfm(body):
    """Rewrite two GitHub habits Python-Markdown reads differently.

    * Nested lists indented by two spaces (GitHub's default) are re-indented to
      the four spaces Python-Markdown requires, so they nest instead of
      flattening. Continuation lines under an item move with it.
    * Blockquotes separated by a blank line are kept separate (Python-Markdown
      would merge them), so each "> [!NOTE]" alert stays its own block.
    Fenced code is left untouched.
    """
    out = []
    stack = []          # [(original_indent, normalized_indent)] of open list items
    in_fence = None
    prev_blank = False
    prev_quote = False
    for line in body.split("\n"):
        fence = _FENCE_RE.match(line)
        if fence and (in_fence is None or line.strip().startswith(in_fence)):
            in_fence = None if in_fence else fence.group(1)
            out.append(line)
            prev_blank = False
            continue
        if in_fence:
            out.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            out.append(line)
            prev_blank = True
            continue

        is_quote = stripped.startswith(">")
        if is_quote and prev_blank and prev_quote:
            out.append("<!-- -->")
            out.append("")
        prev_quote = is_quote

        m = _LIST_ITEM_RE.match(line)
        if m and not is_quote:
            indent = len(m.group(1))
            while stack and stack[-1][0] > indent:
                stack.pop()
            if stack and stack[-1][0] == indent:
                normalized = stack[-1][1]
            elif stack:
                normalized = stack[-1][1] + 4
                stack.append((indent, normalized))
            else:
                normalized = indent
                stack = [(indent, normalized)]
            line = " " * normalized + m.group(2) + m.group(3) + m.group(4)
        elif stack:
            indent = len(line) - len(line.lstrip(" "))
            if indent == 0:
                stack = []
            else:
                owner = max((item for item in stack if item[0] <= indent), key=lambda item: item[0], default=None)
                if owner:
                    line = " " * (indent + owner[1] - owner[0]) + line.lstrip(" ")
        out.append(line)
        prev_blank = False
    return "\n".join(out)


def preprocess_markdown(body):
    """Small rewrites so GitHub/Markdown Viewer-style input reaches the renderer."""
    body = _normalize_gfm(body)
    body = _CITE_FENCE_RE.sub(_cite_fence, body)
    # ```math fences -> $$ blocks (arithmatex understands those).
    body = _MATH_FENCE_RE.sub(lambda m: "$$\n%s\n$$" % m.group(1), body)
    # "$$E=mc^2$$" inside a line of text is display math in Markdown Viewer;
    # arithmatex only treats $$ as a block on its own lines, so make it inline.
    lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith("$$") and stripped.endswith("$$") and stripped != "$$"):
            line = _INLINE_DISPLAY_MATH_RE.sub(lambda m: "$%s$" % m.group(1), line)
        lines.append(line)
    return "\n".join(lines)


def render_markdown_body(text):
    """Markdown text -> HTML fragment (front matter table + body)."""
    data, body = split_front_matter(text)
    head = render_front_matter(data) if data else ""
    return head + markdown.markdown(preprocess_markdown(body), extensions=MD_EXTENSIONS,
                                    extension_configs=MD_EXTENSION_CONFIGS)

# & has to be &amp; inside an HTML attribute.
FONT_LINK_CDN = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    '?family=Inter:wght@300..700'
    '&amp;family=JetBrains+Mono:wght@400..500&amp;display=swap">'
)
FONT_LINK_LOCAL = '<link rel="stylesheet" href="/assets/fonts.css">'


def font_link():
    """Serve fonts from this machine once they have been fetched.

    Checked per request rather than cached at import so `--fetch-assets` takes
    effect without a restart. Matters on a LAN with no internet: the tablet
    cannot reach Google, and without this the pages fall back to system fonts.
    """
    return FONT_LINK_LOCAL if os.path.isfile(FONTS_CSS) else FONT_LINK_CDN


def mermaid_hint():
    """Point READER_JS at a local mermaid build when one is present."""
    if os.path.isfile(MERMAID_JS):
        return "<script>window.__DOCS_MERMAID_SRC='/assets/mermaid.min.js';</script>"
    return ""


def hljs_hint():
    """Point FEATURE_JS at a local highlight.js build when one is present."""
    if os.path.isfile(HLJS_JS):
        return "<script>window.__DOCS_HLJS_SRC='/assets/highlight.min.js';</script>"
    return ""

# Applied before first paint so there is no light/dark or layout flash.
THEME_BOOT = """
<script>
(function () {
  // Dark is the default; the OS preference does not override it. Light is
  // opt-in and only ever set by the toggle.
  var t = localStorage.getItem('docs-theme') || localStorage.getItem('doc-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);

  var w = localStorage.getItem('doc-width') || 'wide';
  document.documentElement.setAttribute('data-width', w);

  var f = localStorage.getItem('docs-font-size');
  if (f) document.documentElement.style.setProperty('--doc-font-size', f + 'px');
})();
</script>
"""

FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%98%3C/text%3E%3C/svg%3E\">"
)


# --------------------------------------------------------------------------
# Document discovery
# --------------------------------------------------------------------------

_meta_cache = {}
_text_cache = {}
_cache_lock = threading.Lock()

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANYTAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)


def plain_text(path):
    """Tag-stripped text of a document, cached on mtime. Used for search."""
    mtime = os.path.getmtime(path)
    with _cache_lock:
        hit = _text_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    if path.endswith(".html"):
        raw = _TAG_RE.sub(" ", raw)
        raw = _ANYTAG_RE.sub(" ", raw)
        raw = html_escape.unescape(raw)
    text = re.sub(r"[ \t]+", " ", raw)

    with _cache_lock:
        _text_cache[path] = (mtime, text)
    return text


def doc_title(path):
    """Best available human title: markdown H1, or <title>/<h1> for HTML."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        head = f.read(8192)

    if path.endswith(".md"):
        for line in head.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    else:
        for rx in (_H1_RE, _TITLE_RE):
            m = rx.search(head)
            if m:
                t = html_escape.unescape(_ANYTAG_RE.sub("", m.group(1))).strip()
                # generate_all_html.py wrote the filename into <title>.
                if t and not t.endswith(".md"):
                    return t

    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.replace("_", " ").replace("-", " ").strip().title()


IGNORE_DIRS = {".venv", "venv", ".git", ".claude", "__pycache__", ".idea", ".vscode", "scratch", "_site"}


def list_docs():
    """One entry per document. A .md shadows its generated .html twin. Supports subdirectories."""
    by_stem = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in IGNORE_DIRS]

        for name in filenames:
            if name.startswith(".") or name in HIDDEN:
                continue
            stem, ext = os.path.splitext(name)
            if ext not in (".md", ".html"):
                continue

            rel_path = os.path.relpath(os.path.join(dirpath, name), ROOT).replace(os.sep, "/")
            rel_stem = os.path.splitext(rel_path)[0]

            # .md is the source of truth; it wins over a stale generated .html.
            if rel_stem in by_stem and by_stem[rel_stem].endswith(".md"):
                continue
            by_stem[rel_stem] = rel_path

    docs = []
    for rel_path in by_stem.values():
        path = os.path.join(ROOT, rel_path)
        try:
            st = os.stat(path)
        except OSError:
            continue

        with _cache_lock:
            hit = _meta_cache.get(rel_path)
        if hit and hit["mtime"] == st.st_mtime:
            docs.append(hit)
            continue

        words = len(plain_text(path).split())
        meta = {
            "file": rel_path,
            "title": doc_title(path),
            "mtime": st.st_mtime,
            # st_birthtime is the real creation time on macOS; elsewhere fall back to mtime.
            "created": getattr(st, "st_birthtime", st.st_mtime),
            "size": st.st_size,
            "words": words,
            "minutes": max(1, round(words / 220)),
            "live": rel_path.endswith(".md"),
            "folder": os.path.dirname(rel_path),
        }
        with _cache_lock:
            _meta_cache[rel_path] = meta
        docs.append(meta)

    # Newest document first, by creation time (not last edit).
    docs.sort(key=lambda d: d.get("created", d["mtime"]), reverse=True)
    return docs


def tree_stamp():
    """Cheap fingerprint of the whole docs tree: newest mtime plus file count.

    Compared once a second by the /__api/watch stream that the library page
    holds open, so a newly dropped .md shows up without a manual refresh.
    """
    newest, count = 0.0, 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in IGNORE_DIRS]
        for name in filenames:
            if name.startswith(".") or not name.endswith((".md", ".html")):
                continue
            try:
                m = os.path.getmtime(os.path.join(dirpath, name))
            except OSError:
                continue
            count += 1
            newest = max(newest, m)
    return (newest, count)


def ago(ts):
    s = time.time() - ts
    for limit, div, unit in (
        (60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h"),
        (2592000, 86400, "d"), (31536000, 2592000, "mo"),
    ):
        if s < limit:
            return "%d%s ago" % (int(s / div), unit)
    return "%dy ago" % int(s / 31536000)


# --------------------------------------------------------------------------
# Reader chrome injected into every document
# --------------------------------------------------------------------------

READER_CSS = """
<style>
%(theme)s
html[data-width="normal"] { --doc-width: 900px; }
html[data-width="wide"]   { --doc-width: 1250px; }
html[data-width="full"]   { --doc-width: 95vw; }

body.docs-reader {
  padding-top: 52px !important;
  font-size: var(--doc-font-size, 16px);
}
body.docs-reader p, body.docs-reader li, body.docs-reader td {
  font-size: var(--doc-font-size, 16px);
}

/* Force container width across pre-rendered HTML and live MD */
.container, main, article, body.docs-reader > div:not(.docs-bar):not(.docs-toc):not(.docs-progress) {
  max-width: var(--doc-width, 1250px) !important;
  transition: max-width .2s ease;
}

/* generate_all_html.py ships its own chrome (top bar, footer, copy buttons).
   The reader bar supersedes all of it, so hide the static copies rather than
   stacking two navs and two Copy buttons on every code block. */
body.docs-reader .top-bar,
body.docs-reader .bottom-bar,
body.docs-reader .copy-btn { display: none !important; }

.docs-bar {
  position: fixed; top: 0; left: 0; right: 0; height: 52px; z-index: 999;
  display: flex; align-items: center; gap: 8px; padding: 0 14px;
  /* Opaque by default. color-mix() sits behind @supports because a var()
     declaration an engine cannot resolve is invalid at computed-value time:
     it resets to transparent rather than falling back to the line above,
     which left the bar unreadable on older tablet browsers. */
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
@supports (background: color-mix(in srgb, red 50%%, transparent)) {
  .docs-bar {
    background: color-mix(in srgb, var(--bg) 86%%, transparent);
    -webkit-backdrop-filter: saturate(180%%) blur(12px);
    backdrop-filter: saturate(180%%) blur(12px);
  }
}
.docs-bar a, .docs-bar button {
  display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 32px;
  padding: 0 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-soft); color: var(--fg); font: 500 13px/1 "Inter", sans-serif;
  cursor: pointer; text-decoration: none; white-space: nowrap; touch-action: manipulation;
}
.docs-bar a:hover, .docs-bar button:hover { border-color: var(--accent); color: var(--accent); }
.docs-bar .docs-title {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 600; color: var(--fg-strong); font-size: 14px;
}
.docs-progress {
  position: fixed; top: 52px; left: 0; height: 2px; width: 0;
  background: var(--accent); z-index: 1000; transition: width .1s linear;
}
/* Table of contents */
.docs-toc {
  position: fixed; top: 52px; bottom: 0; right: 0; width: 290px; z-index: 998;
  overflow-y: auto; padding: 18px 16px 40px; background: var(--bg-soft);
  border-left: 1px solid var(--border); transform: translateX(100%%);
  transition: transform .22s ease;
}
.docs-toc.open { transform: none; }
.docs-toc h4 {
  margin: 0 0 10px; font: 600 11px/1 "Inter", sans-serif; letter-spacing: .08em;
  text-transform: uppercase; color: var(--fg-muted);
}
.docs-toc a {
  display: block; padding: 6px 10px; margin: 1px 0; border-radius: 6px;
  color: var(--fg-muted); font-size: 13px; text-decoration: none;
  border-left: 2px solid transparent; line-height: 1.4;
}
.docs-toc a:hover { background: var(--accent-soft); color: var(--fg); }
.docs-toc a.active { color: var(--accent); border-left-color: var(--accent); background: var(--accent-soft); }
.docs-toc a.lvl3 { padding-left: 24px; font-size: 12px; }
.docs-toc a.lvl4 { padding-left: 38px; font-size: 12px; }
/* Copy button on code blocks */
.docs-pre-wrap { position: relative; }
.docs-copy {
  position: absolute; top: 8px; right: 8px; height: 26px; padding: 0 9px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--bg-raised);
  color: var(--fg-muted); font: 500 11px/1 "Inter", sans-serif; cursor: pointer;
  opacity: 0; transition: opacity .15s;
}
.docs-pre-wrap:hover .docs-copy { opacity: 1; }
.docs-copy.done { color: #3fb950; border-color: #3fb950; opacity: 1; }
/* Mermaid diagrams */
.mermaid {
  text-align: center; margin: 24px 0; background: var(--bg-soft);
  padding: 16px; border-radius: 8px; border: 1px solid var(--border);
  overflow-x: auto; -webkit-overflow-scrolling: touch;
}
.mermaid svg { max-width: 100%%; height: auto; min-width: 300px; }
/* mermaid's built-in dark theme paints subgraph/cluster titles near-black
   (#1f2020) on a dark grey fill (#474949) -- about 1.4:1, unreadable. The
   themeVariables passed at init fix new renders; this covers every label
   regardless of which diagram type drew it. */
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
%(features)s
/* Light-theme overrides for the hard-coded dark palette in generated files */
html[data-theme="light"] body { background: #fff !important; color: #1f2328 !important; }
html[data-theme="light"] h1, html[data-theme="light"] h2,
html[data-theme="light"] h3, html[data-theme="light"] h4,
html[data-theme="light"] strong { color: #010409 !important; }
html[data-theme="light"] code { background: #f6f8fa !important; color: #0550ae !important; }
html[data-theme="light"] pre { background: #f6f8fa !important; border-color: #d1d9e0 !important; }
html[data-theme="light"] pre code { color: #1f2328 !important; }
html[data-theme="light"] a { color: #0969da !important; }
html[data-theme="light"] hr, html[data-theme="light"] td, html[data-theme="light"] th {
  border-color: #d1d9e0 !important;
}
html[data-theme="light"] blockquote { color: #656d76 !important; }
mark.docs-hit { background: var(--mark); color: inherit; border-radius: 3px; padding: 0 2px; }
@media (max-width: 820px) {
  body.docs-reader { padding: 52px 18px 40px !important; }
  .docs-toc { width: 100%%; }
  .docs-bar .docs-hide-sm { display: none; }
}
@media print { .docs-bar, .docs-toc, .docs-progress, .docs-copy { display: none !important; } }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .container, main, article, .docs-toc, .docs-progress, .docs-toast { transition: none !important; }
}
</style>
""" % {"theme": THEME_CSS, "features": FEATURE_CSS}

READER_JS = """
<script>
(function () {
  document.body.classList.add('docs-reader');

  var bar = document.createElement('div');
  bar.className = 'docs-bar';
  bar.innerHTML =
    '<a href="/" title="All documents">\\u2190<span class="docs-hide-sm"> Library</span></a>' +
    '<span class="docs-title"></span>' +
    '<button data-act="font-dec" title="Smaller font (-)" style="padding:0 7px;font-size:11px;">A-</button>' +
    '<button data-act="font-inc" title="Larger font (+)" style="padding:0 7px;font-size:13px;">A+</button>' +
    '<button data-act="width" title="Toggle width: Wide / Full / Normal (w)"><span class="docs-hide-sm">Width: </span><span class="docs-width-label">Wide</span></button>' +
    '<button data-act="toc" title="Contents (c)">\\u2261<span class="docs-hide-sm"> Contents</span></button>' +
    '<button data-act="theme" title="Toggle theme (t)">\\u25D0</button>' +
    '<button data-act="top" title="Back to top">\\u2191</button>';
  document.body.appendChild(bar);
  bar.querySelector('.docs-title').textContent = document.title;

  var widthModes = ['wide', 'full', 'normal'];
  var widthLabels = {'wide': 'Wide', 'full': 'Full', 'normal': 'Normal'};
  var widthLabel = bar.querySelector('.docs-width-label');

  function setDocWidth(w) {
    document.documentElement.setAttribute('data-width', w);
    localStorage.setItem('doc-width', w);
    if (widthLabel) widthLabel.textContent = widthLabels[w] || w;
  }
  var initWidth = localStorage.getItem('doc-width') || 'wide';
  setDocWidth(initWidth);

  var curFont = parseInt(localStorage.getItem('docs-font-size') || '16', 10);
  function setFontSize(sz) {
    curFont = Math.max(13, Math.min(24, sz));
    document.documentElement.style.setProperty('--doc-font-size', curFont + 'px');
    localStorage.setItem('docs-font-size', curFont);
  }
  if (localStorage.getItem('docs-font-size')) setFontSize(curFont);

  // --- Mermaid diagrams ---
  // enhance() strips the CDN <script> out of pre-generated pages, so this is
  // the only code that renders a diagram whichever kind of file is open. Each
  // source block is kept on the div so the diagram can be redrawn on a theme
  // change -- mermaid bakes colours into the SVG and cannot restyle in place.
  function mermaidConfig() {
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
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

  function collectDiagrams() {
    [].slice.call(document.querySelectorAll('pre code.language-mermaid')).forEach(function (el) {
      var pre = el.parentElement;
      // The copy-button pass may already have wrapped this <pre>.
      var host = pre.parentNode;
      var target = host && host.classList && host.classList.contains('docs-pre-wrap') ? host : pre;
      var div = document.createElement('div');
      div.className = 'mermaid';
      div.setAttribute('data-src', el.textContent);
      div.textContent = el.textContent;
      target.parentNode.replaceChild(div, target);
    });
    return [].slice.call(document.querySelectorAll('div.mermaid[data-src]'));
  }

  function renderMermaid(redraw) {
    if (typeof mermaid === 'undefined') return;
    var nodes = collectDiagrams();
    if (!nodes.length) return;
    if (redraw) {
      nodes.forEach(function (d) {
        d.removeAttribute('data-processed');
        d.textContent = d.getAttribute('data-src');
      });
    }
    mermaid.initialize(mermaidConfig());
    try { mermaid.run({ nodes: nodes }); } catch (e) {}
  }

  if (typeof mermaid !== 'undefined') {
    renderMermaid(false);
  } else if (document.querySelector('pre code.language-mermaid')) {
    var ms = document.createElement('script');
    ms.src = window.__DOCS_MERMAID_SRC || 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    ms.onload = function () { renderMermaid(false); };
    document.head.appendChild(ms);
  }

  var progress = document.createElement('div');
  progress.className = 'docs-progress';
  document.body.appendChild(progress);

  // --- Table of contents, built from whatever headings the page has ---
  var toc = document.createElement('nav');
  toc.className = 'docs-toc';
  toc.innerHTML = '<h4>On this page</h4>';
  var heads = [].slice.call(document.querySelectorAll('h2, h3, h4'));
  heads.forEach(function (h, i) {
    if (!h.id) h.id = 'sec-' + i;
    var a = document.createElement('a');
    a.href = '#' + h.id;
    a.textContent = h.textContent;
    a.className = 'lvl' + h.tagName[1];
    a.addEventListener('click', function () {
      if (innerWidth <= 820) toc.classList.remove('open');
    });
    toc.appendChild(a);
  });
  if (heads.length > 1) document.body.appendChild(toc);
  else bar.querySelector('[data-act="toc"]').style.display = 'none';

  var links = [].slice.call(toc.querySelectorAll('a'));

  // --- Scroll: progress bar + active TOC entry ---
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      var max = document.documentElement.scrollHeight - innerHeight;
      progress.style.width = (max > 0 ? (scrollY / max) * 100 : 0) + '%';
      var current = null;
      heads.forEach(function (h) {
        if (h.getBoundingClientRect().top < 120) current = h.id;
      });
      links.forEach(function (a) {
        a.classList.toggle('active', a.getAttribute('href') === '#' + current);
      });
      ticking = false;
    });
  }
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    // Both keys: generate_all_html.py's standalone pages read 'doc-theme', so
    // the choice carries over when the same file is opened straight off disk.
    localStorage.setItem('docs-theme', t);
    localStorage.setItem('doc-theme', t);
    renderMermaid(true);
  }

  bar.addEventListener('click', function (e) {
    var act = e.target.closest('[data-act]');
    if (!act) return;
    act = act.dataset.act;
    if (act === 'toc') toc.classList.toggle('open');
    if (act === 'top') scrollTo({ top: 0, behavior: 'smooth' });
    if (act === 'width') {
      var cw = document.documentElement.getAttribute('data-width') || 'wide';
      var nxt = widthModes[(widthModes.indexOf(cw) + 1) % widthModes.length];
      setDocWidth(nxt);
    }
    if (act === 'font-inc') setFontSize(curFont + 1);
    if (act === 'font-dec') setFontSize(curFont - 1);
    if (act === 'theme') {
      setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
    }
  });

  addEventListener('keydown', function (e) {
    if (e.target.matches('input, textarea')) return;
    if (e.key === 'Escape') { location.href = '/'; }
    if (e.key === 't') bar.querySelector('[data-act="theme"]').click();
    if (e.key === 'w') bar.querySelector('[data-act="width"]').click();
    if (e.key === '+' || e.key === '=') setFontSize(curFont + 1);
    if (e.key === '-' || e.key === '_') setFontSize(curFont - 1);
    if (e.key === 'c') bar.querySelector('[data-act="toc"]').click();
  });

  // --- Highlight + jump to ?q= search term coming from the library page ---
  var q = new URLSearchParams(location.search).get('q');
  if (q) {
    var rx = new RegExp(q.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'), 'gi');
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [], n;
    while ((n = walker.nextNode())) {
      if (n.parentNode.closest('.docs-bar, .docs-toc, script, style')) continue;
      if (rx.test(n.nodeValue)) nodes.push(n);
      rx.lastIndex = 0;
    }
    nodes.forEach(function (node) {
      var span = document.createElement('span');
      span.innerHTML = node.nodeValue.replace(/[&<>]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
      }).replace(rx, function (m) { return '<mark class="docs-hit">' + m + '</mark>'; });
      node.parentNode.replaceChild(span, node);
    });
    var first = document.querySelector('mark.docs-hit');
    if (first) first.scrollIntoView({ block: 'center' });
  }
})();
</script>
"""


# Set from --no-reload; read by enhance(), render_index() and the watch endpoint.
LIVE_RELOAD = True

# Holds one EventSource open per tab. The server answers it only when the file
# (or, on the library page, the tree) changes, so saving a .md on the Mac
# refreshes the tablet without touching it.
RELOAD_JS = """
<script>
(function () {
  if (!window.EventSource) return;
  var file = decodeURIComponent(location.pathname.replace(/^\\//, ''));
  var url = '/__api/watch' + (file ? '?file=' + encodeURIComponent(file) : '');
  var toast, tries = 0;

  function flash(msg) {
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'docs-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    requestAnimationFrame(function () { toast.classList.add('show'); });
  }

  function connect() {
    var es = new EventSource(url);
    es.onopen = function () { tries = 0; };
    es.onmessage = function (e) {
      if (e.data !== 'reload') return;
      es.close();
      flash('Changed \\u2014 reloading');
      setTimeout(function () { location.reload(); }, 150);
    };
    es.onerror = function () {
      // Sleeping tablets and dropped Wi-Fi land here; back off, keep trying.
      es.close();
      tries++;
      setTimeout(connect, Math.min(1000 * tries, 10000));
    };
  }
  connect();
})();
</script>
"""


# generate_all_html.py pulls mermaid from a CDN and renders on load. Served
# through here that render wins the race and bakes in colours READER_JS can no
# longer redraw on a theme change, so the tag is removed and READER_JS renders
# instead. The generated page's own mermaid code is guarded by a
# `typeof mermaid !== 'undefined'` check, so it quietly becomes a no-op.
_MERMAID_TAG_RE = re.compile(
    r'<script[^>]+src=["\'][^"\']*mermaid[^"\']*["\'][^>]*>\s*</script>', re.I
)


# Generated pages carry their own Google Fonts <link>. Strip it and re-add the
# one this server prefers, so a page has exactly one source of fonts and an
# offline tablet is never left waiting on fonts.googleapis.com to resolve.
_GFONT_LINK_RE = re.compile(
    r'<link[^>]*(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>', re.I
)


def enhance(html_text, title_hint=None):
    """Inject reader chrome into a full HTML document."""
    html_text = _MERMAID_TAG_RE.sub("", html_text)
    html_text = _GFONT_LINK_RE.sub("", html_text)
    head_bits = THEME_BOOT + FAVICON + font_link() + mermaid_hint() + hljs_hint() + READER_CSS
    if "</head>" in html_text:
        html_text = html_text.replace("</head>", head_bits + "</head>", 1)
    else:
        html_text = head_bits + html_text

    tail = FEATURE_JS + READER_JS + (RELOAD_JS if LIVE_RELOAD else "")
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", tail + "</body>", 1)
    else:
        html_text += tail

    if title_hint:
        html_text = _TITLE_RE.sub(
            "<title>%s</title>" % html_escape.escape(title_hint), html_text, count=1
        )
    return html_text


# --------------------------------------------------------------------------
# Live markdown rendering
# --------------------------------------------------------------------------

MD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>
body {{ padding: 40px clamp(16px, 3.5vw, 40px); font-size: 16.5px; line-height: 1.75; -webkit-font-smoothing: antialiased; }}
.container {{ max-width: var(--doc-width, 1250px); margin: auto; transition: max-width .2s ease; }}
h1, h2, h3, h4 {{ font-weight: 600; margin: 32px 0 12px; color: var(--fg-strong); line-height: 1.3; }}
h1 {{ font-size: clamp(1.8rem, 2.5vw, 2.2rem); padding-bottom: 8px; border-bottom: 1px solid var(--border); }} h2 {{ font-size: clamp(1.35rem, 2vw, 1.65rem); padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
p {{ margin: 14px 0; font-size: inherit; }}
ul, ol {{ padding-left: 24px; }} li {{ margin: 7px 0; }}
code {{ font-family: "JetBrains Mono", Consolas, monospace; background: var(--bg-soft);
        padding: 3px 6px; border-radius: 6px; font-size: .875em; color: var(--code); }}
pre {{ background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px;
       padding: 16px 18px; overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 14px; line-height: 1.55; }}
pre code {{ background: none; padding: 0; color: var(--fg); font-size: inherit; }}
blockquote {{ margin: 18px 0; padding: 8px 18px; border-left: 4px solid var(--accent); background: var(--bg-soft); color: var(--fg-muted); border-radius: 0 6px 6px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
th, td {{ border: 1px solid var(--border); padding: 10px 14px; text-align: left; font-size: 15px; }}
th {{ background: var(--bg-soft); font-weight: 600; color: var(--fg-strong); }}
tr:nth-child(even) {{ background: var(--bg-soft); }}
hr {{ border: none; border-top: 1px solid var(--border); margin: 35px 0; }}
a {{ color: var(--accent); text-decoration: none; }} a:hover {{ text-decoration: underline; }}
strong {{ color: var(--fg-strong); }}
img {{ max-width: 100%; height: auto; border-radius: 8px; }}
.mermaid {{ text-align: center; margin: 24px 0; background: var(--bg-soft); padding: 16px; border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.mermaid svg {{ max-width: 100%; height: auto; min-width: 320px; }}
</style>
</head>
<body>
<div class="container">
{content}
</div>
</body>
</html>
"""


def render_md(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    body = render_markdown_body(text)
    title = doc_title(path)
    # The font link comes from enhance(), which every .md response goes through.
    return MD_PAGE.format(title=html_escape.escape(title), content=body)


# --------------------------------------------------------------------------
# Library index
# --------------------------------------------------------------------------

def render_index(docs, host):
    cards = []
    for d in docs:
        badge = '<span class="badge live">live md</span>' if d["live"] else ""
        if d.get("folder"):
            badge = ('<span class="badge folder">%s</span>'
                     % html_escape.escape(d["folder"])) + badge
        cards.append(
            '<a class="card" href="/{file}" data-title="{search}">'
            '<div class="card-top"><span class="card-title">{title}</span>{badge}</div>'
            '<div class="card-meta"><span>{minutes} min read</span><span>&middot;</span>'
            '<span>{words:,} words</span><span>&middot;</span><span>{ago}</span></div>'
            '<div class="card-file">{file}</div>'
            "</a>".format(
                file=urllib.parse.quote(d["file"]),
                search=html_escape.escape((d["title"] + " " + d["file"]).lower(), quote=True),
                title=html_escape.escape(d["title"]),
                badge=badge,
                minutes=d["minutes"],
                words=d["words"],
                ago="added " + ago(d.get("created", d["mtime"])),
            )
        )

    total_words = sum(d["words"] for d in docs)
    return INDEX_PAGE.format(
        font=font_link() + mermaid_hint(),
        boot=THEME_BOOT,
        reload=RELOAD_JS if LIVE_RELOAD else "",
        favicon=FAVICON,
        theme=THEME_CSS,
        css=INDEX_CSS,
        cards="\n".join(cards),
        count=len(docs),
        words=total_words,
        minutes=max(1, round(total_words / 220)),
        host=html_escape.escape(host),
    )


# Card grid, search box and theme toggle of the library page. Plain CSS (no
# format placeholders) so build_site.py can drop it into its static index too.
INDEX_CSS = """
.wrap { max-width: 1280px; margin: 0 auto; padding: 48px 24px 80px; }
header { margin-bottom: 28px; }
h1 { margin: 0 0 6px; font-size: 30px; font-weight: 700; color: var(--fg-strong); letter-spacing: -.02em; }
.sub { color: var(--fg-muted); font-size: 14px; }
.sub b { color: var(--fg); font-weight: 600; }
.searchbox { position: relative; margin: 22px 0 8px; }
.searchbox input {
  width: 100%; height: 46px; padding: 0 46px 0 42px; border-radius: 11px;
  border: 1px solid var(--border); background: var(--bg-soft); color: var(--fg);
  font: 400 15px "Inter", sans-serif; outline: none;
}
.searchbox input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.searchbox .icon { position: absolute; left: 15px; top: 13px; color: var(--fg-muted); font-size: 16px; }
.searchbox kbd {
  position: absolute; right: 12px; top: 12px; padding: 3px 7px; font-size: 11px;
  border: 1px solid var(--border); border-radius: 5px; color: var(--fg-muted); background: var(--bg);
}
.hint { font-size: 12.5px; color: var(--fg-muted); min-height: 18px; margin-bottom: 14px; }
.grid { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); }
.card {
  display: block; padding: 16px 18px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-soft); text-decoration: none; color: inherit; transition: .15s;
}
.card:hover { border-color: var(--accent); transform: translateY(-2px); background: var(--bg-raised); }
.card-top { display: flex; align-items: flex-start; gap: 8px; }
.card-title { flex: 1; font-weight: 600; font-size: 15.5px; color: var(--fg-strong); line-height: 1.35; }
.badge {
  font-size: 10px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  padding: 3px 7px; border-radius: 20px; background: var(--accent-soft); color: var(--accent);
  white-space: nowrap;
}
.badge.folder {
  background: var(--bg); border: 1px solid var(--border); color: var(--fg-muted);
  text-transform: none; letter-spacing: 0;
  font-family: "JetBrains Mono", monospace; font-size: 10px;
  max-width: 130px; overflow: hidden; text-overflow: ellipsis;
}
.card-meta { display: flex; gap: 6px; margin-top: 8px; font-size: 12.5px; color: var(--fg-muted); }
.card-file { margin-top: 6px; font-family: "JetBrains Mono", monospace; font-size: 11px;
              color: var(--fg-muted); opacity: .65; overflow: hidden; text-overflow: ellipsis;
              white-space: nowrap; }
.snips { margin-top: 10px; display: grid; gap: 4px; }
.snip { font-size: 12.5px; color: var(--fg-muted); line-height: 1.5;
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.snip mark { background: var(--mark); color: var(--fg-strong); border-radius: 2px; padding: 0 2px; }
.empty { padding: 50px 0; text-align: center; color: var(--fg-muted); }
.themetog {
  position: fixed; top: 16px; right: 16px; width: 36px; height: 36px; border-radius: 9px;
  border: 1px solid var(--border); background: var(--bg-soft); color: var(--fg);
  cursor: pointer; font-size: 15px;
}
footer { margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--border);
          font-size: 12.5px; color: var(--fg-muted); }
footer code { font-family: "JetBrains Mono", monospace; color: var(--code); }
@media (max-width: 600px) { .wrap { padding: 32px 16px 60px; } h1 { font-size: 24px; } }
"""


INDEX_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Docs Library</title>
{font}
{favicon}
{boot}
<style>
{theme}
{css}
</style>
</head>
<body>
<button class="themetog" title="Toggle theme (t)">&#9680;</button>
<div class="wrap">
  <header>
    <h1>Docs Library</h1>
    <div class="sub"><b>{count}</b> documents &middot; <b>{words:,}</b> words &middot; about <b>{minutes} min</b> of reading</div>
  </header>

  <div class="searchbox">
    <span class="icon">&#9906;</span>
    <input id="q" type="search" placeholder="Search titles, or type 2+ characters to search inside every document..."
           autocomplete="off" autofocus>
    <kbd>/</kbd>
  </div>
  <div class="hint" id="hint"></div>

  <div class="grid" id="grid">
{cards}
  </div>
  <div class="empty" id="empty" hidden>Nothing matched.</div>

  <footer>
    Serving <code>{host}</code> &middot; drop a <code>.md</code> in the folder and refresh &mdash; it renders live, no build step.
  </footer>
</div>

<script>
var q = document.getElementById('q'), grid = document.getElementById('grid');
var hint = document.getElementById('hint'), empty = document.getElementById('empty');
var cards = [].slice.call(grid.children);
var timer = null, seq = 0;

function clearSnips() {{
  cards.forEach(function (c) {{
    var s = c.querySelector('.snips');
    if (s) s.remove();
    c.href = c.getAttribute('href').split('?')[0];
  }});
}}

function titleFilter(term) {{
  var shown = 0;
  cards.forEach(function (c) {{
    var hit = !term || c.dataset.title.indexOf(term) > -1;
    c.hidden = !hit;
    if (hit) shown++;
  }});
  return shown;
}}

function run() {{
  var term = q.value.trim().toLowerCase();
  clearSnips();
  if (!term) {{
    titleFilter('');
    hint.textContent = '';
    empty.hidden = true;
    return;
  }}
  var shown = titleFilter(term);
  hint.textContent = shown + (shown === 1 ? ' title matches' : ' titles match');
  empty.hidden = shown > 0;

  if (term.length < 2) return;

  // Full-text search across every document, server-side.
  var mine = ++seq;
  fetch('/__api/search?q=' + encodeURIComponent(term)).then(function (r) {{
    return r.json();
  }}).then(function (data) {{
    if (mine !== seq) return;  // a newer keystroke already won
    var hits = {{}};
    data.results.forEach(function (r) {{ hits[r.file] = r; }});
    var total = 0;
    cards.forEach(function (c) {{
      var file = decodeURIComponent(c.getAttribute('href').split('?')[0].slice(1));
      var hit = hits[file];
      var titleHit = c.dataset.title.indexOf(term) > -1;
      c.hidden = !hit && !titleHit;
      if (!c.hidden) total++;
      if (!hit) return;
      c.href = '/' + encodeURIComponent(file) + '?q=' + encodeURIComponent(term);
      var box = document.createElement('div');
      box.className = 'snips';
      hit.snippets.forEach(function (s) {{
        var d = document.createElement('div');
        d.className = 'snip';
        d.innerHTML = s;  // server escapes, then wraps matches in <mark>
        box.appendChild(d);
      }});
      c.appendChild(box);
    }});
    hint.textContent = total
      ? total + ' document' + (total === 1 ? '' : 's') + ' \\u2014 ' +
        data.results.reduce(function (a, r) {{ return a + r.count; }}, 0) + ' mentions of "' + term + '"'
      : 'No matches for "' + term + '"';
    empty.hidden = total > 0;
  }}).catch(function () {{}});
}}

q.addEventListener('input', function () {{ clearTimeout(timer); timer = setTimeout(run, 140); }});

addEventListener('keydown', function (e) {{
  if (e.key === '/' && document.activeElement !== q) {{ e.preventDefault(); q.focus(); q.select(); }}
  if (e.key === 'Escape' && document.activeElement === q) {{ q.value = ''; run(); q.blur(); }}
  if (e.key === 'Enter' && document.activeElement === q) {{
    var first = cards.find(function (c) {{ return !c.hidden; }});
    if (first) location.href = first.href;
  }}
  if (e.key === 't' && document.activeElement !== q) tog.click();
}});

var tog = document.querySelector('.themetog');
tog.addEventListener('click', function () {{
  var t = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('docs-theme', t);
  localStorage.setItem('doc-theme', t);
}});
</script>
{reload}
</body>
</html>
"""


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def search(term, max_snippets=3):
    rx = re.compile(re.escape(term), re.I)
    results = []
    for meta in list_docs():
        text = plain_text(os.path.join(ROOT, meta["file"]))
        matches = list(rx.finditer(text))
        if not matches:
            continue
        snippets = []
        for m in matches[:max_snippets]:
            a, b = max(0, m.start() - 60), min(len(text), m.end() + 90)
            frag = text[a:b].replace("\n", " ").strip()
            frag = html_escape.escape(frag)
            frag = re.sub(
                re.escape(html_escape.escape(m.group(0))),
                lambda mm: "<mark>%s</mark>" % mm.group(0),
                frag,
                flags=re.I,
            )
            snippets.append(("&hellip;" if a else "") + frag + ("&hellip;" if b < len(text) else ""))
        results.append({
            "file": meta["file"],
            "title": meta["title"],
            "count": len(matches),
            "snippets": snippets,
        })
    results.sort(key=lambda r: r["count"], reverse=True)
    return results


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

NOT_FOUND = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found</title>{font}{boot}<style>{theme}
.c {{ max-width: 520px; margin: 18vh auto; padding: 0 20px; text-align: center; }}
h1 {{ font-size: 64px; margin: 0; color: var(--fg-muted); }}
p {{ color: var(--fg-muted); }}
a {{ display: inline-block; margin-top: 18px; padding: 10px 18px; border-radius: 9px;
     border: 1px solid var(--border); background: var(--bg-soft); color: var(--accent);
     text-decoration: none; font-weight: 500; }}
code {{ color: var(--code); }}
</style></head><body><div class="c"><h1>404</h1>
<p><code>{path}</code> isn't here.</p><a href="/">Back to the library</a></div></body></html>"""


class Handler(SimpleHTTPRequestHandler):
    server_version = "DocsServer/1.0"

    # Python's mimetypes table predates woff2 on some systems.
    extensions_map = dict(SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update({
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
    })

    def __init__(self, *a, **kw):
        SimpleHTTPRequestHandler.__init__(self, *a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        if self.command == "GET" and not self.path.startswith("/__api"):
            sys.stdout.write("  %s %s\n" % (self.command, urllib.parse.unquote(self.path)))
            sys.stdout.flush()

    def _send(self, body, status=200, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Always re-read from disk so an edited file shows up on refresh.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    WATCH_POLL = 1.0  # seconds between mtime checks on an open watch stream

    def _watch(self, rel):
        """Server-sent events: one 'reload' the moment the watched file changes.

        With no ?file=, watches the whole tree -- that is what the library page
        uses so a new document appears without a refresh. The stream is held
        open and answers at most once; the client reconnects on its own.
        """
        if not LIVE_RELOAD:
            return self._send("live reload disabled", status=404,
                              ctype="text/plain; charset=utf-8")
        if self.command == "HEAD":
            # Never block a HEAD on a stream that only speaks when a file changes.
            return self._send("", ctype="text/event-stream; charset=utf-8")

        full = self._safe_path("/" + rel) if rel else None
        if rel and (not full or not os.path.isfile(full)):
            return self._send("no such file", status=404,
                              ctype="text/plain; charset=utf-8")

        def stamp():
            if full is None:
                return tree_stamp()
            try:
                return os.path.getmtime(full)
            except OSError:
                return None  # mid-write or briefly gone; wait it out

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        last = stamp()
        try:
            while True:
                time.sleep(self.WATCH_POLL)
                now = stamp()
                if now is not None and now != last:
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                    return
                # Keepalive, so a tablet's Wi-Fi power saving does not drop us.
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # tab closed or navigated away

    def _safe_path(self, url_path):
        """Resolve a URL path inside ROOT, or None if it escapes."""
        rel = urllib.parse.unquote(url_path.split("?", 1)[0].lstrip("/"))
        rel = posixpath.normpath(rel)
        if rel.startswith("..") or os.path.isabs(rel):
            return None
        full = os.path.realpath(os.path.join(ROOT, rel))
        if full != ROOT and not full.startswith(ROOT + os.sep):
            return None
        return full

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path == "/":
            host = self.headers.get("Host", "localhost")
            return self._send(render_index(list_docs(), host))

        if path == "/__api/search":
            term = urllib.parse.parse_qs(parsed.query).get("q", [""])[0].strip()
            payload = {"results": search(term) if len(term) >= 2 else []}
            return self._send(
                json.dumps(payload), ctype="application/json; charset=utf-8"
            )

        if path == "/__api/watch":
            rel = urllib.parse.parse_qs(parsed.query).get("file", [""])[0]
            return self._watch(rel)

        if path == "/__api/docs":
            return self._send(
                json.dumps(list_docs()), ctype="application/json; charset=utf-8"
            )

        full = self._safe_path(path)
        if not full or not os.path.isfile(full):
            return self._send(
                NOT_FOUND.format(
                    font=font_link(), boot=THEME_BOOT, theme=THEME_CSS,
                    path=html_escape.escape(urllib.parse.unquote(path)),
                ),
                status=404,
            )

        raw = "raw" in urllib.parse.parse_qs(parsed.query)

        if full.endswith(".md"):
            if raw:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    return self._send(f.read(), ctype="text/plain; charset=utf-8")
            return self._send(enhance(render_md(full)))

        if full.endswith(".html"):
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            if raw:
                return self._send(text)
            return self._send(enhance(text, title_hint=doc_title(full)))

        # images, css, anything else
        return SimpleHTTPRequestHandler.do_GET(self)

    do_HEAD = do_GET


_PRIVATE_RE = re.compile(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)")
_HWPORT_RE = re.compile(r"Hardware Port:\s*(.+?)\s*\nDevice:\s*(\S+)")


def _mac_hardware_ports():
    """[(label, device)] for real NICs. Excludes VPN utunN, which is the point:
    Tailscale/WireGuard own the default route, so a route-based guess hands the
    tablet an address it cannot reach."""
    try:
        out = subprocess.check_output(
            ["networksetup", "-listallhardwareports"], stderr=subprocess.DEVNULL
        ).decode()
    except Exception:
        return [("Wi-Fi", "en0"), ("Ethernet", "en1"), ("Ethernet", "en2")]
    return _HWPORT_RE.findall(out)


def _ifaddr(device):
    try:
        ip = subprocess.check_output(
            ["ipconfig", "getifaddr", device], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None
    return ip or None


def _route_ip():
    """Whatever address would be used to reach the internet. Works everywhere,
    but on a Mac running a VPN it is often the wrong one for LAN clients."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the route
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def lan_addresses():
    """[(label, ip)] of every address a phone or tablet might reach, best first."""
    found, seen = [], set()

    if sys.platform == "darwin":
        for label, device in _mac_hardware_ports():
            ip = _ifaddr(device)
            if ip and not ip.startswith("127.") and ip not in seen:
                seen.add(ip)
                found.append(("%s / %s" % (label, device), ip))

    ip = _route_ip()
    if ip and not ip.startswith("127.") and ip not in seen:
        seen.add(ip)
        found.append(("default route", ip))

    # Wi-Fi first, then anything on a private subnet -- that is what the tablet
    # is actually on. Docker bridges and VPN addresses sink to the bottom.
    found.sort(key=lambda item: (
        0 if "Wi-Fi" in item[0] else 1,
        0 if _PRIVATE_RE.match(item[1]) else 1,
    ))
    return found or [("loopback", "127.0.0.1")]


def lan_ip():
    """The single best address to print and encode in the QR code."""
    return lan_addresses()[0][1]


def fetch_assets():
    """Download the web fonts, mermaid and highlight.js into ./assets for offline use.

    Without this, a tablet rendering a page has to reach fonts.googleapis.com
    and jsDelivr itself. On a Wi-Fi network with no internet -- or one where
    the tablet is captive-portalled -- text falls back to a system font and
    diagrams silently do not render. Once these files exist, font_link() and
    the mermaid hint point at this machine instead, and nothing is fetched
    from outside the LAN.
    """
    import urllib.request

    # Google serves woff2 only to browsers it recognises; a urllib UA gets ttf.
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }

    def get(url):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    fonts_dir = os.path.join(ASSETS_DIR, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    total = 0

    print("\n  Fetching assets into %s\n" % ASSETS_DIR)

    print("  font stylesheet ...", end=" ", flush=True)
    css = get(GOOGLE_FONTS_URL).decode("utf-8")
    print("ok")

    urls = sorted(set(re.findall(r"url\((https://[^)]+\.woff2)\)", css)))
    for i, url in enumerate(urls, 1):
        # Opaque hashed basenames can repeat across families; keep the family
        # and version segments so two files never collide.
        name = re.sub(r"[^A-Za-z0-9._-]", "-", url.split("/s/")[-1])
        dest = os.path.join(fonts_dir, name)
        if os.path.isfile(dest):
            size = os.path.getsize(dest)
        else:
            data = get(url)
            with open(dest, "wb") as f:
                f.write(data)
            size = len(data)
        total += size
        print("  font %2d/%d  %-46s %6.1f KB" % (i, len(urls), name[:46], size / 1024.0))
        css = css.replace(url, "/assets/fonts/" + name)

    with open(FONTS_CSS, "w", encoding="utf-8") as f:
        f.write(css)
    print("  wrote assets/fonts.css")

    print("  mermaid ...", end=" ", flush=True)
    data = get(MERMAID_URL)
    with open(MERMAID_JS, "wb") as f:
        f.write(data)
    total += len(data)
    print("%.1f KB" % (len(data) / 1024.0))

    print("  highlight.js ...", end=" ", flush=True)
    data = get(HLJS_URL)
    with open(HLJS_JS, "wb") as f:
        f.write(data)
    total += len(data)
    print("%.1f KB" % (len(data) / 1024.0))

    print("\n  Done -- %.1f KB total. Pages now load fonts, diagrams and code colours from "
          "this machine.\n" % (total / 1024.0))


def print_qr(url):
    try:
        import qrcode
    except ImportError:
        print("  (install qrcode for a scannable QR: pip install qrcode)\n")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    print(buf.getvalue())


def main():
    ap = argparse.ArgumentParser(description="Serve this docs folder on the local network.")
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)")
    ap.add_argument("--no-qr", action="store_true", help="skip the QR code")
    ap.add_argument("--no-reload", action="store_true",
                    help="do not auto-refresh open pages when a file changes")
    ap.add_argument("--fetch-assets", action="store_true",
                    help="download fonts + mermaid + highlight.js into ./assets, then exit "
                         "(lets the server work with no internet)")
    args = ap.parse_args()

    if args.fetch_assets:
        try:
            fetch_assets()
        except Exception as e:
            sys.exit("  Could not fetch assets: %s" % e)
        return

    global LIVE_RELOAD
    LIVE_RELOAD = not args.no_reload

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        sys.exit("Cannot bind %s:%d -- %s\nTry: python serve.py --port %d"
                 % (args.host, args.port, e, args.port + 1))
    httpd.daemon_threads = True

    addrs = lan_addresses()
    label, ip = addrs[0]
    url = "http://%s:%d" % (ip, args.port)
    docs = list_docs()

    print("\n  \033[1mDocs Library\033[0m -- %d documents from %s\n" % (len(docs), ROOT))
    print("  On this Mac    \033[36mhttp://localhost:%d\033[0m" % args.port)
    print("  Phone / tablet \033[1;36m%s\033[0m   (%s)" % (url, label))
    for other_label, other_ip in addrs[1:]:
        print("     or fallback \033[36mhttp://%s:%d\033[0m   (%s)"
              % (other_ip, args.port, other_label))
    print("  Auto-reload    %s" % ("on" if LIVE_RELOAD else "off (--no-reload)"))
    local_fonts = os.path.isfile(FONTS_CSS)
    local_mermaid = os.path.isfile(MERMAID_JS)
    local_hljs = os.path.isfile(HLJS_JS)
    if local_fonts and local_mermaid and local_hljs:
        print("  Assets         local (works with no internet)\n")
    else:
        missing = [n for n, ok in (("fonts", local_fonts), ("mermaid", local_mermaid),
                                   ("highlight.js", local_hljs)) if not ok]
        print("  Assets         %s from CDN -- run "
              "\033[36mpython serve.py --fetch-assets\033[0m to self-host\n"
              % " and ".join(missing))
    if not args.no_qr:
        print_qr(url)
    print("  Ctrl+C to stop\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
