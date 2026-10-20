import os
import glob

# Configuration
TITLE = "My Notes"
CSS = """
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 1rem; line-height: 1.6; background: #f9f9f9; }
h1 { text-align: center; color: #333; }
ul { list-style: none; padding: 0; }
li { margin: 0.6rem 0; font-size: 1.15rem; }
a { color: #0066cc; text-decoration: none; }
a:hover { text-decoration: underline; color: #004080; }
.note { color: #555; font-size: 0.95rem; font-family: monospace; }
"""

def generate_index():
    html_files = sorted(glob.glob("**/*.html", recursive=True))  # finds all .html in current + subfolders

    if not html_files:
        print("No .html files found in this directory or subdirectories.")
        return

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{TITLE}</title>
  <style>{CSS}</style>
</head>
<body>
  <h1>{TITLE}</h1>
  <ul>
"""

    for file_path in html_files:
        # Clean display name: remove .md, replace _/- with space, capitalize words
        display_name = os.path.splitext(file_path)[0].replace('_', ' ').replace('-', ' ').title()
        html += f'    <li><a href="{file_path}">{display_name}</a></li>\n'

    html += """  </ul>
  <hr>
  <p style="text-align: center; font-size: 0.9rem; color: #777;">
    Generated automatically • Refresh page after adding new files (or re-run generate_index.py)
  </p>
</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated index.html with {len(html_files)} Markdown files.")
    print("Restart your server (Ctrl+C then rerun) or refresh the page.")

if __name__ == "__main__":
    generate_index()