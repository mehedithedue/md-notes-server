# MD Notes Server

A small set of Python scripts that turn a folder of Markdown notes into
styled HTML pages, build a clickable index, and serve everything on your
local network so you can read your notes from a phone or tablet.

```
notes.md ──► generate_all_html.py ──► notes.html
                                          │
             generate_index.py ───────► index.html (links to every .html)
                                          │
             serve_md.py ─────────────► http://<your-ip>:8080  (+ QR code)
```

## Scripts

| Script | What it does |
| --- | --- |
| `generate_all_html.py` | Converts every `.md` file in the current folder to a dark-themed `.html` page. Skips any file that already has an `.html` version. |
| `generate_index.py` | Scans the folder (and subfolders) for `.html` files and writes an `index.html` with a link to each one. |
| `serve_md.py` | Starts a web server on port `8080`, detects your local network IP, and prints the URL plus a QR code you can scan from another device. |

## Requirements

- Python 3.8+
- [`markdown`](https://pypi.org/project/Markdown/) — needed by `generate_all_html.py`
- [`qrcode`](https://pypi.org/project/qrcode/) — optional, for the terminal QR code

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

Put your `.md` files in the project folder, then run the three steps in order:

```bash
python3 generate_all_html.py   # 1. Markdown → HTML
python3 generate_index.py      # 2. Build index.html
python3 serve_md.py            # 3. Serve on the local network
```

Open the printed URL (for example `http://192.168.1.20:8080`) or scan the QR
code from a device on the same Wi-Fi. Press `Ctrl+C` to stop the server.

### Updating notes

- **New note:** run steps 1 and 2 again, then refresh the browser.
- **Edited note:** delete its old `.html` file first — `generate_all_html.py`
  never overwrites an existing page.

## Configuration

Settings are constants at the top of each script:

| Setting | File | Default |
| --- | --- | --- |
| `PORT` | `serve_md.py` | `8080` |
| `TITLE` | `generate_index.py` | `"My Notes"` |
| `CSS` | `generate_index.py` | Light theme for the index page |
| `TEMPLATE` | `generate_all_html.py` | Dark theme (Inter font) for note pages |

## Notes and limitations

- The server shares **everything** in the folder with anyone on your network.
  Only run it on networks you trust.
- `index.html` lists itself after the first run, since it is also an `.html` file.
- If you restart the server right away you may see `Address already in use`;
  wait a few seconds or change `PORT`.
- Markdown extensions enabled: `extra`, `tables`, `fenced_code`, `toc`.
