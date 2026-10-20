#!/usr/bin/env python3
"""Build a static copy of the docs library for S3 (or any static host).

serve.py does its work per request: it renders .md on the fly, injects the
reader bar into every page, builds the library index and answers full-text
searches. S3 can run none of that, so this script does all of it ahead of
time and writes the result into ./_site:

    _site/index.html       library page: cards, title search, full-text search
    _site/search.json      plain text of every document, read by that search
    _site/<doc>.html       every document with the reader bar baked in
    _site/assets/...       fonts, mermaid and highlight.js, served from the bucket

    python3 build_site.py                            # build into ./_site
    python3 build_site.py --sort created             # order by creation date
    python3 build_site.py --deploy s3://my-bucket    # build, then upload
    python3 build_site.py --deploy s3://my-bucket --prune   # also delete removed docs

Every link is relative and names index.html explicitly, because the plain
bucket endpoint (https://<bucket>.s3.<region>.amazonaws.com/) does not serve
an index document for "/". Open the site at .../index.html.

Compared to serve.py the only thing missing is live reload: there is no
server left to watch the files. Rebuild and redeploy instead.

The bucket needs a public-read bucket policy (or CloudFront in front of it)
and the AWS CLI must be installed and signed in (`brew install awscli`,
then `aws configure`).
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime
from string import Template

# Everything that defines the look of a page lives in serve.py; reuse it so
# the static site and the LAN server never drift apart.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve  # noqa: E402

ROOT = serve.ROOT
OUT = os.path.join(ROOT, "_site")
MARKER = os.path.join(OUT, ".build_site")   # proves _site is ours before it is wiped
TITLE = "Docs Library"


# --------------------------------------------------------------------------
# Per-page chrome, with relative URLs instead of serve.py's root-relative ones
# --------------------------------------------------------------------------

def font_link(prefix):
    if os.path.isfile(serve.FONTS_CSS):
        return '<link rel="stylesheet" href="%sassets/fonts.css">' % prefix
    return serve.FONT_LINK_CDN


def mermaid_hint(prefix):
    if os.path.isfile(serve.MERMAID_JS):
        return "<script>window.__DOCS_MERMAID_SRC='%sassets/mermaid.min.js';</script>" % prefix
    return ""


def hljs_hint(prefix):
    if os.path.isfile(serve.HLJS_JS):
        return "<script>window.__DOCS_HLJS_SRC='%sassets/highlight.min.js';</script>" % prefix
    return ""


def reader_js(prefix):
    """serve.py's reader bar points "home" at "/", which S3 cannot resolve."""
    home = prefix + "index.html"
    js = serve.READER_JS
    for old, new in (
        ('<a href="/" title="All documents">', '<a href="%s" title="All documents">' % home),
        ("location.href = '/';", "location.href = '%s';" % home),
    ):
        if js.count(old) != 1:
            sys.exit("serve.READER_JS changed; cannot find %r to rewrite." % old)
        js = js.replace(old, new)
    return js


def enhance(html_text, prefix, title_hint=None):
    """Static twin of serve.enhance(): same chrome, relative links, no reload."""
    html_text = serve._MERMAID_TAG_RE.sub("", html_text)
    html_text = serve._GFONT_LINK_RE.sub("", html_text)
    head_bits = (serve.THEME_BOOT + serve.FAVICON + font_link(prefix)
                 + mermaid_hint(prefix) + hljs_hint(prefix) + serve.READER_CSS)
    if "</head>" in html_text:
        html_text = html_text.replace("</head>", head_bits + "</head>", 1)
    else:
        html_text = head_bits + html_text

    tail = serve.FEATURE_JS + reader_js(prefix)
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", tail + "</body>", 1)
    else:
        html_text += tail

    if title_hint:
        html_text = serve._TITLE_RE.sub(
            "<title>%s</title>" % html.escape(title_hint), html_text, count=1)
    return html_text


# --------------------------------------------------------------------------
# Library index with in-browser search
# --------------------------------------------------------------------------

INDEX_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
$font
$favicon
$boot
<style>
$theme
$css
</style>
</head>
<body>
<button class="themetog" title="Toggle theme (t)">&#9680;</button>
<div class="wrap">
  <header>
    <h1>$title</h1>
    <div class="sub"><b>$count</b> documents &middot; <b>$words</b> words &middot; about <b>$minutes min</b> of reading</div>
  </header>

  <div class="searchbox">
    <span class="icon">&#9906;</span>
    <input id="q" type="search" placeholder="Search titles, or type 2+ characters to search inside every document..."
           autocomplete="off" autofocus>
    <kbd>/</kbd>
  </div>
  <div class="hint" id="hint"></div>

  <div class="grid" id="grid">
$cards
  </div>
  <div class="empty" id="empty" hidden>Nothing matched.</div>

  <footer>
    Built $built &middot; sorted by $sort date, newest first &middot; rebuild with <code>python3 build_site.py --deploy</code>
  </footer>
</div>

<script>
var q = document.getElementById('q'), grid = document.getElementById('grid');
var hint = document.getElementById('hint'), empty = document.getElementById('empty');
var cards = [].slice.call(grid.children);
var timer = null, seq = 0;

// search.json holds the plain text of every document. It is fetched once,
// the first time someone types two or more characters.
var index = null, loading = null;
function loadIndex() {
  if (index) return Promise.resolve(index);
  if (!loading) {
    loading = fetch('search.json').then(function (r) { return r.json(); }).then(function (d) {
      d.forEach(function (doc) { doc.low = doc.text.toLowerCase(); });
      index = d;
      return d;
    });
  }
  return loading;
}

function esc(s) {
  return s.replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; });
}
function escRe(s) { return s.replace(/[.*+?^{}()|[\\]\\\\]/g, '\\\\$$&'); }

// Same shape as serve.py's /__api/search: hit count plus up to three snippets.
function matchDoc(doc, term) {
  var count = 0, snippets = [], pos = 0, rx = new RegExp(escRe(term), 'gi');
  while ((pos = doc.low.indexOf(term, pos)) > -1) {
    if (snippets.length < 3) {
      var a = Math.max(0, pos - 60), b = Math.min(doc.text.length, pos + term.length + 90);
      var frag = esc(doc.text.slice(a, b).trim()).replace(rx, function (m) { return '<mark>' + m + '</mark>'; });
      snippets.push((a ? '\\u2026' : '') + frag + (b < doc.text.length ? '\\u2026' : ''));
    }
    count++;
    pos += term.length;
  }
  return count ? { count: count, snippets: snippets } : null;
}

function clearSnips() {
  cards.forEach(function (c) {
    var s = c.querySelector('.snips');
    if (s) s.remove();
    c.href = c.dataset.href;
  });
}

function titleFilter(term) {
  var shown = 0;
  cards.forEach(function (c) {
    var hit = !term || c.dataset.title.indexOf(term) > -1;
    c.hidden = !hit;
    if (hit) shown++;
  });
  return shown;
}

function run() {
  var term = q.value.trim().toLowerCase();
  clearSnips();
  if (!term) {
    titleFilter('');
    hint.textContent = '';
    empty.hidden = true;
    return;
  }
  var shown = titleFilter(term);
  hint.textContent = shown + (shown === 1 ? ' title matches' : ' titles match');
  empty.hidden = shown > 0;

  if (term.length < 2) return;

  var mine = ++seq;
  hint.textContent += index ? '' : ' \\u00b7 loading full-text index\\u2026';
  loadIndex().then(function (docs) {
    if (mine !== seq) return;  // a newer keystroke already won
    var hits = {}, mentions = 0;
    docs.forEach(function (doc) {
      var hit = matchDoc(doc, term);
      if (hit) { hits[doc.file] = hit; mentions += hit.count; }
    });
    var total = 0;
    cards.forEach(function (c) {
      var hit = hits[c.dataset.file];
      var titleHit = c.dataset.title.indexOf(term) > -1;
      c.hidden = !hit && !titleHit;
      if (!c.hidden) total++;
      if (!hit) return;
      c.href = c.dataset.href + '?q=' + encodeURIComponent(term);
      var box = document.createElement('div');
      box.className = 'snips';
      hit.snippets.forEach(function (s) {
        var d = document.createElement('div');
        d.className = 'snip';
        d.innerHTML = s;  // text is escaped above; only our <mark> tags survive
        box.appendChild(d);
      });
      c.appendChild(box);
    });
    hint.textContent = total
      ? total + ' document' + (total === 1 ? '' : 's') + ' \\u2014 ' + mentions + ' mentions of "' + term + '"'
      : 'No matches for "' + term + '"';
    empty.hidden = total > 0;
  }).catch(function () {
    hint.textContent += ' \\u00b7 full-text search unavailable';
  });
}

q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 140); });

addEventListener('keydown', function (e) {
  if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); q.select(); }
  if (e.key === 'Escape' && document.activeElement === q) { q.value = ''; run(); q.blur(); }
  if (e.key === 'Enter' && document.activeElement === q) {
    var first = cards.find(function (c) { return !c.hidden; });
    if (first) location.href = first.href;
  }
  if (e.key === 't' && document.activeElement !== q) tog.click();
});

var tog = document.querySelector('.themetog');
tog.addEventListener('click', function () {
  var t = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('docs-theme', t);
  localStorage.setItem('doc-theme', t);
});
</script>
</body>
</html>
""")


def render_index(docs, sort):
    cards = []
    for d in docs:
        badge = '<span class="badge live">from md</span>' if d["live"] else ""
        if d["folder"]:
            badge = '<span class="badge folder">%s</span>' % html.escape(d["folder"]) + badge
        cards.append(
            '<a class="card" href="{href}" data-href="{href}" data-file="{file}" data-title="{search}">'
            '<div class="card-top"><span class="card-title">{title}</span>{badge}</div>'
            '<div class="card-meta"><span>{minutes} min read</span><span>&middot;</span>'
            '<span>{words:,} words</span><span>&middot;</span><span>{date}</span></div>'
            '<div class="card-file">{file}</div>'
            "</a>".format(
                href=urllib.parse.quote(d["out"]),
                file=html.escape(d["out"], quote=True),
                search=html.escape((d["title"] + " " + d["out"]).lower(), quote=True),
                title=html.escape(d["title"]),
                badge=badge,
                minutes=d["minutes"],
                words=d["words"],
                date=d["when"].strftime("%b %d, %Y"),
            )
        )

    total_words = sum(d["words"] for d in docs)
    return INDEX_PAGE.substitute(
        title=TITLE,
        font=font_link("") + mermaid_hint(""),
        favicon=serve.FAVICON,
        boot=serve.THEME_BOOT,
        theme=serve.THEME_CSS,
        css=serve.INDEX_CSS,
        cards="\n".join(cards),
        count=len(docs),
        words="{:,}".format(total_words),
        minutes=max(1, round(total_words / 220)),
        built=datetime.now().strftime("%Y-%m-%d %H:%M"),
        sort=sort,
    )


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def doc_when(path, sort):
    st = os.stat(path)
    # st_birthtime is the real creation time on macOS; elsewhere fall back to mtime.
    ts = getattr(st, "st_birthtime", st.st_mtime) if sort == "created" else st.st_mtime
    return datetime.fromtimestamp(ts)


def collect_docs(sort):
    docs = []
    for d in serve.list_docs():
        src = os.path.join(ROOT, d["file"])
        d = dict(d)
        d["src"] = src
        d["out"] = os.path.splitext(d["file"])[0] + ".html"   # a .md becomes .html
        d["when"] = doc_when(src, sort)
        docs.append(d)
    docs.sort(key=lambda d: d["when"], reverse=True)
    return docs


def reset_out():
    if os.path.isdir(OUT):
        if not os.path.isfile(MARKER):
            sys.exit("%s exists but was not made by this script; move it away first." % OUT)
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    with open(MARKER, "w") as f:
        f.write("output of build_site.py; safe to delete\n")


def write(rel, text):
    dest = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)


def copy_assets():
    if not os.path.isdir(serve.ASSETS_DIR):
        return False
    dest = os.path.join(OUT, "assets")
    shutil.copytree(serve.ASSETS_DIR, dest)
    # fonts.css was written for the LAN server with /assets/fonts/... URLs.
    # Relative to assets/fonts.css the same files are at fonts/...
    css_path = os.path.join(dest, "fonts.css")
    if os.path.isfile(css_path):
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(css.replace("url(/assets/fonts/", "url(fonts/"))
    return True


def build(sort):
    docs = collect_docs(sort)
    if not docs:
        print("No .md or .html files found.")
        return False

    reset_out()
    search = []
    for d in docs:
        prefix = "../" * d["out"].count("/")
        if d["live"]:
            page = enhance(serve.render_md(d["src"]), prefix)
        else:
            with open(d["src"], encoding="utf-8", errors="replace") as f:
                page = enhance(f.read(), prefix, title_hint=d["title"])
        write(d["out"], page)
        search.append({
            "file": d["out"],
            "title": d["title"],
            "text": " ".join(serve.plain_text(d["src"]).split()),
        })

    write("index.html", render_index(docs, sort))
    write("search.json", json.dumps(search, ensure_ascii=False))
    local_assets = copy_assets()

    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print("Built %d documents into %s (%.1f MB, assets %s)." % (
        len(docs), os.path.relpath(OUT, ROOT), size / 1e6,
        "self-hosted" if local_assets else "from CDN"))
    return True


# --------------------------------------------------------------------------
# Deploy
# --------------------------------------------------------------------------

def sync(target, prune, filters, **headers):
    cmd = ["aws", "s3", "sync", OUT, target, "--exclude", ".build_site"] + filters
    for k, v in headers.items():
        cmd += ["--" + k.replace("_", "-"), v]
    if prune:
        cmd.append("--delete")
    return subprocess.call(cmd) == 0


def site_url(target):
    """Best guess at the public URL, for the closing message only."""
    bucket, _, prefix = target[len("s3://"):].partition("/")
    region = "us-east-1"
    try:
        out = subprocess.check_output(
            ["aws", "s3api", "get-bucket-location", "--bucket", bucket, "--output", "text"],
            stderr=subprocess.DEVNULL).decode().strip()
        if out and out != "None":
            region = out
    except (subprocess.CalledProcessError, OSError):
        pass
    path = prefix.strip("/")
    return "https://%s.s3.%s.amazonaws.com/%sindex.html" % (
        bucket, region, path + "/" if path else "")


def deploy(target, prune):
    if not target.startswith("s3://"):
        sys.exit("--deploy expects an s3:// URI, got %r" % target)
    if not shutil.which("aws"):
        sys.exit("The AWS CLI is not installed. On a Mac: brew install awscli, then aws configure.")

    print("Uploading to %s ..." % target)
    # Three passes so each kind of file gets the right headers. Pages and the
    # search index are revalidated on every load, so a redeploy shows up at
    # once; fonts and mermaid are cached for a day.
    ok = (
        sync(target, prune, ["--exclude", "*", "--include", "*.html", "--include", "*.json"],
             cache_control="no-cache")
        and sync(target, prune, ["--exclude", "*", "--include", "*.woff2"],
                 content_type="font/woff2", cache_control="public, max-age=86400")
        and sync(target, prune, ["--exclude", "*.html", "--exclude", "*.json", "--exclude", "*.woff2"],
                 cache_control="public, max-age=86400")
    )
    if ok:
        print("Done. Open %s" % site_url(target))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sort", choices=["modified", "created"], default="created",
                    help="which date orders the library page (default: created, like serve.py)")
    ap.add_argument("--deploy", metavar="S3_URI", help="e.g. s3://my-docs-bucket or s3://bucket/prefix")
    ap.add_argument("--prune", action="store_true",
                    help="with --deploy: delete objects in the bucket that are no longer in _site")
    args = ap.parse_args()

    if not build(args.sort):
        return 1
    if args.deploy and not deploy(args.deploy, args.prune):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
