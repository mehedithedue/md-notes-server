# AGENTS.md

Read this first. It tells you what this repo is, where the logic lives, and
what not to touch, so you do not have to search the whole folder.

## What this is

A personal docs library. Markdown notes about work tickets live in this
folder, and a few Python scripts render and serve them. Only the scripts are
versioned. The notes, the rendered pages, the `_site/` build and the fetched
`assets/` are gitignored and exist only on the owner's machine.

Do not treat the `.md` / `.html` files as part of the codebase. They are
content. Never commit them, never bulk-edit or delete them, and never run a
command that rewrites them unless the task is explicitly about a note.

## Files that matter

| File | Role |
| --- | --- |
| `serve.py` | The core. Shared Markdown renderer, page chrome (reader bar, theme, feature JS/CSS), LAN server on port 8000 with live reload, library index, full-text search, `--fetch-assets`. Everything else imports from it. ~1900 lines. |
| `build_site.py` | Static build of the whole library into `_site/` for S3. Reuses `serve.py` for rendering and chrome, rewrites links to be relative. Keeps `.build_history.json` (content hashes) to badge cards as "new" / "updated". `--deploy s3://bucket` uploads with the AWS CLI. |
| `generate_all_html.py` | Writes a standalone `.html` next to each `.md` for reading off disk. Timestamp-based skip, `-f` forces. Imports the renderer from `serve.py`. |
| `generate_index.py` | Static `index.html` for browsing off disk. `serve.py` builds a richer index on its own, so this is a fallback. |
| `requirements.txt` | `markdown`, `pymdown-extensions`, `pyyaml`, `qrcode`. |
| `.venv/` | The working virtualenv (Python 3.9). Use `.venv/bin/python`. |

## Where to look for what

- **How a page is rendered (Markdown → HTML):** `serve.py`, `render_markdown_body()` and `render_md()`. Extensions, alerts, front matter, Kroki fences live there.
- **Page look and feel (CSS, theme toggle, width toggle, copy buttons, Mermaid):** `serve.py` constants `THEME_CSS`, `READER_CSS`, `READER_JS`, `FEATURE_CSS`, `FEATURE_JS`, `THEME_BOOT`. `build_site.py` reuses them and only rewrites the home link.
- **Which files appear in the library:** `serve.py`, `list_docs()`. A `.md` shadows its `.html` twin. `HIDDEN` and `IGNORE_DIRS` are near the top and are mirrored in `generate_index.py`; keep them in step.
- **Library index page (cards, search):** `serve.py` for the live server, `build_site.py` `INDEX_PAGE` / `render_index()` for the static one. They share `INDEX_CSS`.
- **New / updated badges on the static index:** `build_site.py`, `collect_docs()` and `load_history()` / `save_history()`.
- **S3 upload and cache headers:** `build_site.py`, `deploy()` and `sync()`.
- **Self-hosted fonts / Mermaid / highlight.js:** `serve.py`, `fetch_assets()`. Output goes to `assets/`, which `build_site.py` copies into `_site/assets/`.

## Rules

- Keep `serve.py` the single source of truth for rendering and chrome. If a
  page feature is added, add it there, not in `build_site.py` or
  `generate_all_html.py`. `build_site.py` asserts on the exact strings it
  rewrites in `READER_JS`, so changing that markup needs a matching edit.
- `build_site.py` wipes `_site/` before building. It refuses unless the
  `_site/.build_site` marker is present. Do not remove that guard.
- `.build_history.json` at the repo root is build state, gitignored. Deleting
  it only resets the badges; the next build reseeds from file dates.
- Keep `.gitignore` exceptions minimal: `README.md`, `AGENTS.md` and
  `CLAUDE.md` are the only Markdown files tracked.
- No tests exist. Verify changes by running the script:
  `.venv/bin/python build_site.py` or `.venv/bin/python serve.py --no-qr --port 8777`
  and checking the output in `_site/` or with `curl`.
- Commit messages are plain English, present tense, first line under 72
  characters.

## Quick commands

```bash
.venv/bin/python serve.py                  # LAN server, http://<ip>:8000
.venv/bin/python serve.py --fetch-assets   # self-host fonts, mermaid, highlight.js
.venv/bin/python build_site.py             # static build into _site/
.venv/bin/python build_site.py --sort updated --deploy s3://bucket --prune
.venv/bin/python generate_all_html.py -f   # regenerate every .html on disk
```
