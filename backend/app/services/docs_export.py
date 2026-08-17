"""Document PDF export (Improvements Plan Stage 17) — reuses the exact same
markdown -> HTML -> weasyprint pipeline as JAR Analyser's change-report PDF
(app/services/jar_analyser/change_report.py), the one existing genuine
server-rendered PDF path in this app, rather than introducing a second
PDF-generation approach or a new dependency (weasyprint/markdown are
already in requirements.txt).

Docs content is different from change_report's input though — it's raw,
freeform markdown an operator typed, not programmatically-assembled
structured data — so this module also has to do two things change_report.py
never needed to:

  - Convert wiki-links (`[[Doc]]`) and callouts (`> [!NOTE]`) into something
    python-markdown understands, mirroring MarkdownPreview.tsx's own
    preprocessMarkdown() (duplicated here in Python rather than shared,
    matching this codebase's per-module convention for small helpers — see
    e.g. bug_similarity.py's own docstring on the same point).
  - Strip literal HTML tags from the *rendered-outside-fences* portion of
    the content before handing it to python-markdown, which (unlike
    react-markdown here, which has no rehype-raw plugin wired in) passes
    raw HTML straight through by default. Doc content is operator-authored,
    not fully untrusted, but weasyprint fetches remote resources (e.g. a
    stray `<img src="http://...">`) when rendering — an SSRF surface this
    export path would otherwise introduce that the existing frontend
    rendering deliberately doesn't have. Fenced code blocks are exempt, so
    a real `<div>...</div>` example in a ```html snippet still renders as
    the code sample it's meant to be.

Mermaid diagrams are NOT rendered — PDF export has no browser/JS engine —
so a mermaid fence renders as its own raw source text inside a code block.
Documented as a known limitation in the Help guide rather than a silent gap.
"""
from __future__ import annotations

import html as html_lib
import re

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _preprocess_wikilinks(text: str) -> str:
    def repl(m: re.Match) -> str:
        target, label = m.group(1), m.group(2)
        display = (label or target).strip()
        return f"**{display}**"
    return _WIKILINK_RE.sub(repl, text)


_CALLOUT_LABELS = {
    "NOTE": "ℹ️ Note", "TIP": "\U0001f4a1 Tip", "WARNING": "⚠️ Warning",
    "IMPORTANT": "❗ Important", "CAUTION": "\U0001f536 Caution", "DANGER": "\U0001f6a8 Danger",
}
_CALLOUT_RE = re.compile(r"^> ?\[!(\w+)\]\s*$", re.MULTILINE | re.IGNORECASE)


def _preprocess_callouts(text: str) -> str:
    def repl(m: re.Match) -> str:
        label = _CALLOUT_LABELS.get(m.group(1).upper())
        return f"> **{label}**" if label else m.group(0)
    return _CALLOUT_RE.sub(repl, text)


# Only matches genuine tag-shaped sequences (`<div>`, `</div>`, `<img ...>`)
# — never a bare `>` on its own, so real markdown blockquotes (including the
# callout markers above, already converted by the time this runs) are
# untouched.
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s+[^<>]*)?/?>")


def _strip_html_tags(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


_FENCE_RE = re.compile(r"(^|\n)([ \t]*(?:```|~~~)[^\n]*\n[\s\S]*?\n[ \t]*(?:```|~~~)[ \t]*(?=\n|$))")


def _transform_outside_fences(text: str, transform) -> str:
    result: list[str] = []
    last_index = 0
    for m in _FENCE_RE.finditer(text):
        fence_start = m.start() + len(m.group(1))
        result.append(transform(text[last_index:fence_start]))
        result.append(m.group(2))
        last_index = fence_start + len(m.group(2))
    result.append(transform(text[last_index:]))
    return "".join(result)


def _preprocess_markdown(text: str) -> str:
    return _transform_outside_fences(
        text, lambda seg: _strip_html_tags(_preprocess_wikilinks(_preprocess_callouts(seg)))
    )


_CSS = """
@page {
    size: A4;
    margin: 20mm 18mm 20mm 18mm;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9pt;
        color: #888;
    }
}
body {
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #1a1a1a;
}
h1 { font-size: 20pt; color: #1e3a5f; border-bottom: 2px solid #1e3a5f; padding-bottom: 4pt; margin-top: 0; }
h2 { font-size: 14pt; color: #1e3a5f; border-bottom: 1px solid #c0cfe0; padding-bottom: 2pt; margin-top: 18pt; }
h3 { font-size: 12pt; color: #2c5282; margin-top: 14pt; }
h4 { font-size: 10pt; color: #2d3748; margin-top: 10pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; }
th { background: #1e3a5f; color: white; padding: 5pt 8pt; text-align: left; }
td { padding: 4pt 8pt; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafc; }
code, pre { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; background: #f0f4f8; padding: 1pt 3pt; border-radius: 2pt; }
pre { padding: 6pt; display: block; white-space: pre-wrap; }
blockquote {
    border-left: 4px solid #4a90d9;
    background: #f0f6fc;
    margin: 10pt 0;
    padding: 8pt 12pt;
    color: #1a3a5c;
}
ul, ol { margin: 4pt 0; padding-left: 16pt; }
li { margin: 2pt 0; }
strong { color: #1a1a1a; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 12pt 0; }
.doc-meta {
    font-size: 9pt;
    color: #666;
    margin-bottom: 12pt;
    padding-bottom: 8pt;
    border-bottom: 1px solid #e2e8f0;
}
"""


def doc_to_pdf(
    title: str, content: str, library_name: str, shelf_name: str,
    version: int, updated_at: str,
) -> bytes:
    """Render a document's current version as a PDF byte string."""
    import markdown as md_lib
    import weasyprint

    body_md = _preprocess_markdown(content)
    html_body = md_lib.markdown(body_md, extensions=["tables", "fenced_code", "nl2br"])

    title_esc = html_lib.escape(title)
    meta = (
        f'<p class="doc-meta">\U0001f4da {html_lib.escape(library_name)} / {html_lib.escape(shelf_name)}'
        f' &nbsp;·&nbsp; v{version} &nbsp;·&nbsp; Updated {html_lib.escape(updated_at)}</p>'
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title_esc}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{title_esc}</h1>
{meta}
{html_body}
</body>
</html>"""
    return weasyprint.HTML(string=html).write_pdf()


def about_to_pdf(content: str, updated_by: str | None, updated_at: str | None) -> bytes:
    """Render the About page as a PDF — same pipeline as doc_to_pdf, minus
    the library/shelf/version meta line an About page doesn't have. Kept
    as a thin sibling rather than generalising doc_to_pdf's signature,
    since the two meta lines don't share enough shape to be worth forcing
    into one parameter set."""
    import markdown as md_lib
    import weasyprint

    body_md = _preprocess_markdown(content)
    html_body = md_lib.markdown(body_md, extensions=["tables", "fenced_code", "nl2br"])

    meta = ""
    if updated_by and updated_at:
        meta = f'<p class="doc-meta">Last updated by {html_lib.escape(updated_by)} on {html_lib.escape(updated_at)}</p>'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>About</title>
<style>{_CSS}</style>
</head>
<body>
<h1>About</h1>
{meta}
{html_body}
</body>
</html>"""
    return weasyprint.HTML(string=html).write_pdf()
