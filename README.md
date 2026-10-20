# MD Notes Server

A small set of Python scripts that turn a folder of Markdown notes into
styled HTML pages, serve them on your local network (with live reload), and
optionally build a static copy for S3 or any plain file host.

```
notes.md ──► serve.py ──────────► http://<your-ip>:8000   (live render, LAN, QR code)
         ──► generate_all_html.py ──► notes.html           (static page on disk)
         ──► build_site.py ─────────► _site/               (static site, deployable to S3)
```

Only the tooling is versioned. Your notes (`.md`), the rendered pages
(`.html`), the `_site/` build and the downloaded `assets/` are ignored by git
and stay on your machine.

## Scripts

| Script | What it does |
| --- | --- |
| `serve.py` | The main tool. Serves the folder on port `8000`, renders every `.md` on request, builds the library index page with full-text search, and reloads open pages when a file is saved. Prints the LAN URL plus a QR code. Also holds the shared renderer and page chrome used by the other scripts. |
| `generate_all_html.py` | Converts `.md` files to standalone `.html` pages for reading straight off disk. Skips files whose page is newer than the source. |
| `generate_index.py` | Writes a static `index.html` listing every `.html` page. Only needed when browsing off disk; `serve.py` builds its own richer index. |
| `build_site.py` | Builds the whole library into `_site/` (pages, index, `search.json`, assets), badges new and updated documents, and can upload it to an S3 bucket. |

## Requirements

- Python 3.8+
- `markdown`, `pymdown-extensions`, `pyyaml` for rendering
- `qrcode` (optional) for the terminal QR code

All of them are in `requirements.txt`.

## Setup

```bash
git clone https://github.com/mehedithedue/md-notes-server.git
cd md-notes-server

python3 -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
                                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

### Read notes on the LAN (most common)

Put your `.md` files in the project folder, then:

```bash
python3 serve.py                 # http://<your-lan-ip>:8000
python3 serve.py --port 9000
python3 serve.py --no-qr         # skip the QR code
python3 serve.py --no-reload     # drop the live-reload watcher
python3 serve.py --host 127.0.0.1   # local machine only
```

Open the printed URL or scan the QR code from a device on the same Wi-Fi.
Editing a `.md` and saving it reloads the page on the other device. New files
show up on the next refresh. Press `Ctrl+C` to stop.

### Work offline

By default pages load fonts, Mermaid and highlight.js from CDNs. To self-host
them so the LAN server works without internet:

```bash
python3 serve.py --fetch-assets
```

This fills `assets/` (fonts, `mermaid.min.js`, `highlight.min.js`). Kroki
diagrams and MathJax still need internet.

### Static pages on disk

```bash
python3 generate_all_html.py            # every .md in the folder
python3 generate_all_html.py notes.md   # just these files
python3 generate_all_html.py -r         # include subfolders
python3 generate_all_html.py -f         # force rebuild, ignore timestamps
python3 generate_all_html.py --index    # also rebuild index.html afterwards
python3 generate_index.py               # rebuild index.html only
```

### Static site for S3

```bash
python3 build_site.py                            # build into ./_site
python3 build_site.py --sort updated             # last content change first (default: created)
python3 build_site.py --fresh-days 14            # badge anything new/changed in 2 weeks (default: 7)
python3 build_site.py --deploy s3://my-bucket    # build, then upload
python3 build_site.py --deploy s3://my-bucket --prune   # also delete removed docs
```

Each build stores a content hash of every source in `.build_history.json`
(gitignored, next to the scripts). On the next build a card shows a **new**
badge if the document first appeared recently, or an **updated** badge with
its change date if the text changed recently. This tracks real content
changes, not file timestamps, so regenerating pages or checking out a branch
does not mark everything as updated. Delete the file to reset; the next build
reseeds from file dates.

Deploying needs the AWS CLI installed and signed in (`brew install awscli`,
then `aws configure`) and a bucket with a public-read policy or CloudFront in
front of it. Open the site at `.../index.html`; the plain bucket endpoint does
not serve an index document for `/`.

## Rendering

GitHub-flavoured Markdown (tables, task lists, strikethrough, autolinks,
emoji, footnotes, definition lists), YAML front matter shown as a table,
`> [!NOTE]`-style alerts, highlight.js code colouring with a language label
and copy button, Mermaid, PlantUML / D2 / Graphviz / Vega-Lite / WaveDrom
fences via kroki.io, and LaTeX math via MathJax. Dark theme by default with a
light toggle and a width toggle on every page.

All three outputs (LAN server, pages on disk, `_site/`) share the same
renderer in `serve.py`, so they look identical.

## Configuration

Settings are constants at the top of each script:

| Setting | File | Default |
| --- | --- | --- |
| `--port` flag | `serve.py` | `8000` |
| `HIDDEN` | `serve.py`, `generate_index.py` | `index.html`, `sample.html` are left out of the index |
| `IGNORE_DIRS` | `serve.py`, `generate_index.py` | `.venv`, `venv`, `.git`, `.claude`, `_site`, … |
| `TITLE` | `build_site.py`, `generate_index.py` | `"Docs Library"` |
| `OUT` | `build_site.py` | `./_site` |

## Notes and limitations

- The server shares **everything** in the folder with anyone on your network.
  Only run it on networks you trust, or bind with `--host 127.0.0.1`.
- `build_site.py` wipes `_site/` before each build. It checks for its own
  marker file first, so it will refuse to delete a folder it did not create.
- If you restart the server right away you may see `Address already in use`;
  wait a few seconds or pick another `--port`.
