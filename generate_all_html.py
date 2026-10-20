import os
import markdown
import traceback

# HTML template
TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />

<title>{{TITLE}}</title>

<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">

<style>
body {
  margin:0;
  padding:40px;
  background:#0d1117;
  color:#e6edf3;
  font-family:"Inter", sans-serif;
  line-height:1.7;
}

.container {
  max-width:850px;
  margin:auto;
}

h1,h2,h3,h4 {
  font-weight:600;
  margin-top:32px;
  margin-bottom:12px;
}

p {
  margin:12px 0;
  font-size:16px;
}

ul {
  padding-left:22px;
}

li {
  margin:6px 0;
}

code {
  font-family:Consolas, monospace;
  background:#161b22;
  padding:3px 6px;
  border-radius:6px;
  font-size:14px;
  color:#79c0ff;
}

hr {
  border:none;
  border-top:1px solid #30363d;
  margin:35px 0;
}

a {
  color:#58a6ff;
  text-decoration:none;
}

a:hover {
  text-decoration:underline;
}

strong {
  color:#f0f6fc;
}
</style>
</head>

<body>
<div class="container">
{{CONTENT}}
</div>
</body>
</html>
"""


def convert_md(md_file):
    try:
        print(f"Processing {md_file}...")

        html_file = md_file.replace(".md", ".html")

        if os.path.exists(html_file):
            print(f"Skipping {md_file} (HTML exists)")
            return

        # read markdown
        with open(md_file, "r", encoding="utf-8") as f:
            md_text = f.read()

        # convert markdown
        html_content = markdown.markdown(
            md_text,
            extensions=["extra", "tables", "fenced_code", "toc"]
        )

        # inject into template safely
        final_html = TEMPLATE.replace("{{TITLE}}", md_file)\
                             .replace("{{CONTENT}}", html_content)

        # write html
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(final_html)

        print(f"Generated {html_file}")

    except FileNotFoundError:
        print(f"[ERROR] File not found: {md_file}")

    except PermissionError:
        print(f"[ERROR] Permission denied for file: {md_file}")

    except Exception as e:
        print(f"[ERROR] Failed processing {md_file}")
        print("Reason:", str(e))
        print("\nTraceback:")
        traceback.print_exc()


def main():
    for file in os.listdir("."):
        if file.endswith(".md"):
            convert_md(file)

if __name__ == "__main__":
    main()