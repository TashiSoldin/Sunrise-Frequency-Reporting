"""Render a Markdown document to a branded PDF (Sunrise Logistics · sam et al.).

    python md_to_pdf.py "path\\to\\doc.md" [--out "path\\to\\doc.pdf"] [--section-pages]

The look is the handover-document pipeline Akha uses elsewhere (Gelasio body,
monospace code, title block with brand line and stamp, footer with the title
and page x / y), ported to what this box can run:

* WeasyPrint needs Pango and Cairo, which are not installed here and need an
  admin to install, so the Microsoft Edge already on the box prints the page,
  driven by Playwright (channel "msedge": nothing is downloaded). Playwright
  is the one package, pulled in by `uv run --with playwright` from the bat.
  Chromium's own header/footer templates draw the footer.
* Graphviz is not installed, so ```mermaid blocks are rendered in the page by
  mermaid.js before printing. It loads from jsdelivr, so a render needs the
  internet; the fonts are local (assets/fonts/gelasio, OFL).
* A small Markdown-to-HTML converter covers what the project's documents use
  (ATX headings, paragraphs, bullet and numbered lists, pipe tables,
  blockquotes, fenced code, horizontal rules, inline code / bold / italic /
  links), so no markdown package is needed.

Document conventions (same as the source pipeline):

* The first `# ` heading is the title and is removed from the body; the title
  block renders it.
* An emphasised line directly under it — `*like this*`, not `**bold**` — is
  the subtitle. It may wrap over several lines. Audience labels in a
  `·`-separated subtitle (client-facing, internal, do not share ...) are
  dropped: they instruct the sender, not the reader.
* `**Document version X**` as the next line becomes the stamp; otherwise the
  stamp is "Current as of <today>".
* `- [ ]` / `- [x]` become checklist boxes.

assets/md_to_pdf_template.html holds all styling; this file holds none.
"""

from __future__ import annotations

import argparse
import datetime
import html
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
TEMPLATE = REPO / "assets" / "md_to_pdf_template.html"
FONTS = REPO / "assets" / "fonts"
BRAND = "Sunrise Logistics · sam et al."

# Pack sources label who a document is for. That label is an instruction to
# the sender, not part of the document, and printing it on a page the client
# reads is worse than useless.
AUDIENCE_MARKER = re.compile(
    r"^(client[- ]facing|internal|akha only|do not share|confidential)$", re.IGNORECASE
)


# --------------------------------------------------------------------------
# Inline markdown
# --------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_AUTOLINK = re.compile(r"(?<![\"'>=\w])(https?://[^\s<)]+)")


def inline(text: str) -> str:
    """Convert inline markdown. Code spans are protected from the other rules."""
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(stash, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _AUTOLINK.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


# --------------------------------------------------------------------------
# Block markdown
# --------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HRULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    line = line.removeprefix("|")
    line = line.removesuffix("|")
    return [c.strip() for c in line.split("|")]


def _table_align(sep: str) -> list[str]:
    out = []
    for cell in _split_row(sep):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "right" if right else "left")
    return out


def _is_block_start(lines: list[str], i: int) -> bool:
    s = lines[i]
    return bool(
        _HEADING.match(s)
        or _BULLET.match(s)
        or _NUMBERED.match(s)
        or _HRULE.match(s)
        or s.strip().startswith(("```", ">"))
        or ("|" in s and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]))
    )


def to_html(md: str) -> str:
    """Body HTML for markdown that has already had its title block removed."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Fenced code; ```mermaid becomes a diagram rendered in the page.
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip().lower()
            block = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            code = html.escape("\n".join(block))
            if lang == "mermaid":
                out.append(
                    f'<div class="diagram"><pre class="mermaid">{code}</pre></div>'
                )
            else:
                out.append(f"<pre><code>{code}</code></pre>")
            continue

        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if _HRULE.match(line):
            out.append("<hr>")
            i += 1
            continue

        # Table: header row followed by a separator row
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            header = _split_row(line)
            align = _table_align(lines[i + 1])
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1

            def cell(tag: str, k: int, c: str) -> str:
                a = align[k] if k < len(align) else "left"
                return f'<{tag} style="text-align:{a}">{inline(c)}</{tag}>'

            out.append("<table>")
            out.append(
                "<thead><tr>"
                + "".join(cell("th", k, c) for k, c in enumerate(header))
                + "</tr></thead>"
            )
            out.append("<tbody>")
            for r in rows:
                out.append(
                    "<tr>"
                    + "".join(cell("td", k, c) for k, c in enumerate(r))
                    + "</tr>"
                )
            out.append("</tbody></table>")
            continue

        if line.lstrip().startswith(">"):
            block = []
            while i < n and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(block))}</p></blockquote>")
            continue

        if _BULLET.match(line) or _NUMBERED.match(line):
            i = _emit_list(lines, i, out)
            continue

        # Paragraph: run of non-blank lines that do not start another block
        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines, i):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")

    return "\n".join(out)


def _emit_list(lines: list[str], i: int, out: list[str]) -> int:
    """Emit a (possibly nested) list starting at line i. Returns the next index."""
    n = len(lines)
    stack: list[tuple[int, str]] = []  # (indent, tag)

    def close_to(indent: int) -> None:
        while stack and stack[-1][0] > indent:
            out.append(f"</li></{stack.pop()[1]}>")

    while i < n:
        line = lines[i]
        m = _BULLET.match(line) or _NUMBERED.match(line)
        if not m:
            # A blank line ends the list unless the next non-blank line is another item.
            if not line.strip():
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if (
                    j < n
                    and (_BULLET.match(lines[j]) or _NUMBERED.match(lines[j]))
                    and stack
                ):
                    i = j
                    continue
                break
            # Continuation line of the current item
            if stack and line.startswith(" "):
                out[-1] = out[-1] + " " + inline(line.strip())
                i += 1
                continue
            break
        indent = len(m.group(1).replace("\t", "    "))
        tag = "ol" if _NUMBERED.match(line) else "ul"
        text = inline(m.group(2))
        if not stack or indent > stack[-1][0]:
            stack.append((indent, tag))
            out.append(f"<{tag}><li>{text}")
        else:
            close_to(indent)
            if stack and stack[-1][0] == indent:
                out.append(f"</li><li>{text}")
            else:
                stack.append((indent, tag))
                out.append(f"<{tag}><li>{text}")
        i += 1

    close_to(-1)
    return i


# --------------------------------------------------------------------------
# Title block: title, subtitle, stamp
# --------------------------------------------------------------------------


def subtitle_block(lines: list[str]) -> tuple[str, int] | None:
    """The emphasised run directly under the heading, unwrapped.

    Returns (subtitle, lines consumed) or None. `*like this*` or `_like this_`
    opening on the first non-blank line and closing on that line or a later
    one. `**bold**` is body text and never a subtitle.
    """
    buf: list[str] = []
    mark = ""
    for k, line in enumerate(lines):
        s = line.strip()
        if not s and not buf:
            continue
        if not buf:
            if len(s) < 3 or s[0] not in "*_" or s[1] == s[0]:
                return None
            mark = s[0]
        if not s:
            return None
        buf.append(s)
        joined = " ".join(buf)
        if len(joined) > 3 and joined[-1] == mark and joined[-2] != mark:
            return joined[1:-1].strip(), k + 1
    return None


def strip_audience_markers(subtitle: str) -> str:
    parts = [s.strip() for s in subtitle.split("·")]
    kept = [s for s in parts if s and not AUDIENCE_MARKER.match(s)]
    return " · ".join(kept)


def split_front_matter(md: str, fallback_title: str) -> tuple[str, str, str, str]:
    """Return (title, subtitle, stamp, body_markdown)."""
    lines = md.replace("\r\n", "\n").split("\n")
    title, subtitle, stamp = fallback_title, "", ""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        title = re.sub(r"^\d+\s*·\s*", "", lines[i][2:]).strip()
        i += 1
        found = subtitle_block(lines[i:])
        if found:
            subtitle = strip_audience_markers(found[0])
            i += found[1]
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        ver = re.match(r"^\*\*Document version ([^*]+)\*\*\s*$", lines[i].strip())
        if ver:
            stamp = f"Document version {ver.group(1).strip()}"
            i += 1
    if not stamp:
        today = datetime.date.today()
        stamp = f"Current as of {today.day} {today:%B %Y}"
    body = "\n".join(lines[i:])
    body = body.replace("- [ ]", "- ☐").replace("- [x]", "- ☑")
    return title, subtitle, stamp, body


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def build_page(md_path: Path, section_pages: bool) -> str:
    title, subtitle, stamp, body_md = split_front_matter(
        md_path.read_text(encoding="utf-8"), md_path.stem
    )
    body = to_html(body_md)
    page = TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("{{title}}", html.escape(title))
        .replace("{{subtitle}}", html.escape(subtitle))
        .replace("{{stamp}}", html.escape(stamp))
        .replace("{{brand}}", html.escape(BRAND))
        .replace("{{fonts}}", FONTS.resolve().as_uri())
        .replace("{{section_pages}}", "section-pages" if section_pages else "")
        .replace("{{body}}", body)
    )


FOOTER = """
<div style="font-family: Georgia, 'Times New Roman', serif; font-size: 7.5pt; color: #999;
            width: 100%; padding: 0 18mm; display: flex; justify-content: space-between;">
  <span>{title}</span>
  <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
</div>
"""


def render(md_path: Path, pdf_path: Path, section_pages: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "Playwright is not in this environment. Run through run_md_to_pdf.bat, "
            "or: uv run --with playwright md_to_pdf.py ..."
        )

    title = split_front_matter(md_path.read_text(encoding="utf-8"), md_path.stem)[0]
    page_html = build_page(md_path, section_pages)

    # The page is written to a temp folder so its file:// URL can reach the
    # local fonts; the PDF goes to a temp file first so a failed print never
    # leaves a half-written file where the real one was.
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / (md_path.stem + ".html")
        html_path.write_text(page_html, encoding="utf-8")
        tmp_pdf = Path(tmp) / "out.pdf"
        with sync_playwright() as pw:
            # channel="msedge" is the Edge already on the box: nothing downloads.
            browser = pw.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page()
                errors: list[str] = []
                page.on(
                    "console",
                    lambda m: errors.append(m.text) if m.type == "error" else None,
                )
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                # Set by the template once mermaid has drawn every diagram.
                page.wait_for_function("window.__ready === true", timeout=60_000)
                page.emulate_media(media="print")
                page.pdf(
                    path=str(tmp_pdf),
                    format="A4",
                    prefer_css_page_size=True,
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=FOOTER.format(title=html.escape(title)),
                    margin={
                        "top": "22mm",
                        "right": "18mm",
                        "bottom": "20mm",
                        "left": "18mm",
                    },
                )
            finally:
                browser.close()
        if errors:
            print(
                "Browser console errors during the render:\n  " + "\n  ".join(errors),
                file=sys.stderr,
            )
        pdf_path.write_bytes(tmp_pdf.read_bytes())


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render a Markdown document to a branded PDF."
    )
    ap.add_argument("markdown", type=Path, help="the .md file to render")
    ap.add_argument(
        "--out", type=Path, help="the .pdf to write (default: beside the .md)"
    )
    ap.add_argument(
        "--section-pages",
        action="store_true",
        help="start every ## section on a new page (long handover documents)",
    )
    ap.add_argument(
        "--html",
        type=Path,
        help="also write the intermediate HTML here (for a look in a browser)",
    )
    args = ap.parse_args()

    md_path: Path = args.markdown
    if not md_path.exists():
        sys.exit(f"Not found: {md_path}")
    pdf_path: Path = args.out or md_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if args.html:
        args.html.write_text(build_page(md_path, args.section_pages), encoding="utf-8")
    render(md_path, pdf_path, args.section_pages)
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
