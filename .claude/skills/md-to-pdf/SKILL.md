---
name: md-to-pdf
description: Render a Markdown document to the branded Sunrise Logistics · sam et al. PDF (Gelasio body, title block, footer with page numbers, Mermaid diagrams) for sending to Reuven, Larry, Innate or Parcel Perfect. Use when asked to turn a .md into a PDF, to attach a document to an email, or to redo a client-facing document's PDF.
---

# Markdown to branded PDF

The tool is `md_to_pdf.py` at the repo root, wrapped by `run_md_to_pdf.bat`.
The look lives in `assets/md_to_pdf_template.html`; the fonts in
`assets/fonts/gelasio` (OFL). Change the look in the template, not the script.

## Run it

```
run_md_to_pdf.bat "path\to\document.md"                 # PDF beside the .md
run_md_to_pdf.bat "path\to\document.md" "out.pdf"
run_md_to_pdf.bat "path\to\document.md" "" --section-pages   # every ## on a new page
```

From a shell without the bat: `uv run --with playwright md_to_pdf.py "doc.md" [--out x.pdf] [--html debug.html]`.
The PDF replaces an existing one. `--html` also writes the intermediate page,
useful for a look in a browser.

## How it works, and why

- WeasyPrint cannot load on the BI server (no Pango or Cairo, and Akha is not
  admin), so the Edge already on the box prints the page, driven by Playwright
  with `channel="msedge"`. Nothing downloads except the Playwright package,
  which `uv run --with playwright` caches once. Do not switch to plain
  `msedge --headless --print-to-pdf`: it will not overwrite an existing file,
  hangs when Akha's Edge window holds the profile lock, and prints before
  Mermaid has drawn.
- Diagrams: a ```mermaid fence is rendered in the page by mermaid.js from
  jsdelivr, so a render needs the internet. The template sets `window.__ready`
  when the diagrams are drawn and the script waits for it.
- Footer (title · page x / y) comes from Chromium's own footer template in
  `page.pdf()`; `@page` margin boxes are ignored by Chromium.
- Mermaid ignores `direction` inside a subgraph that has edges to the outside;
  prefer a single multi-line node over a subgraph when that happens.

## Document conventions

- First `# ` heading = the title (rendered in the title block, removed from
  the body).
- An italic line directly under it, `*Sunrise Logistics · prepared for X · date*`,
  = the subtitle. `**bold**` is body text, not a subtitle. Audience labels
  (client-facing, internal, do not share, confidential) are dropped.
- `**Document version X**` as the next line = the stamp; otherwise the stamp
  is "Current as of <today>".
- Client-facing documents: plain language, no code, no credentials, hostnames
  or ports, and no domain claims about the business (see the Claude Briefing
  page in Coda).

## Afterwards

- Check the page count and look at the output; a "one page" brief that comes
  out at three needs cutting, not a smaller font.
- The Tooling Registry (Coda, Scripts and tooling table) has a row for this
  tool; update it if the tool changes. A delivered document goes in the
  "Deliverables and where they land" table once it has been sent.
