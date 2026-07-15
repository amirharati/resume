# CV Builder

This repo turns a single source resume into two maintainable outputs:

- a short resume for normal job applications
- a complete resume with the full source inventory preserved for review and pruning

Current workflow decision:

- `complete` is the source of truth we edit first.
- `short` will be derived later from the cleaned `complete` version.

## Goals

- Keep one structured source of truth for your background.
- Maintain both short and complete resume versions without editing a PDF by hand.
- Generate readable Markdown plus polished PDF outputs locally.
- Make it easy for an AI agent to update facts, rebalance emphasis, and prune outdated content over time.

## Project Layout

- `source/`: original source material, including your current PDF
- `data/profile.yaml`: structured master profile
- `variants/`: resume variants such as `short` and `complete`
- `templates/resume.md.j2`: readable markdown export
- `templates/resume.html.j2`: print-focused HTML template for the styled PDF layout
- `scripts/render_cv.py`: render Markdown and PDF for a chosen variant
- `scripts/render_pdf_playwright.js`: isolated Playwright PDF renderer
- `scripts/fetch_url.py`: generic raw/rendered URL fetch helper for future source gathering
- `scripts/fetch_url_playwright.js`: Playwright-backed rendered page fetch helper
- `output/`: generated user-facing files
- `tmp/`: optional verification artifacts when we inspect PDFs

## Quick Start

Install the JavaScript dependency used by the styled PDF renderer:

```bash
npm install
```

Produce the complete reference resume from the structured source:

```bash
python3 scripts/render_cv.py complete
```

This reads from:

- `data/profile.yaml`
- `variants/complete.yaml`

and writes:

- `output/markdown/complete.md`
- `output/pdf/amir_harati_complete_resume.pdf`

Render alternate complete-resume templates:

```bash
python3 scripts/render_cv.py complete_single_column
python3 scripts/render_cv.py complete_classic
python3 scripts/render_cv.py complete_hybrid
python3 scripts/render_cv.py complete_ats
```

These produce:

- `output/pdf/amir_harati_complete_resume_single_column.pdf`
- `output/pdf/amir_harati_complete_resume_classic.pdf`
- `output/pdf/amir_harati_complete_resume_hybrid.pdf`
- `output/pdf/amir_harati_complete_resume_ats.pdf`

Render the short resume:

```bash
python3 scripts/render_cv.py short
```

Generate Markdown only:

```bash
python3 scripts/render_cv.py complete --markdown-only
```

Fetch a source URL for later cleanup work:

```bash
python3 scripts/fetch_url.py "https://example.com"
python3 scripts/fetch_url.py "https://example.com" --rendered
```

For JS-heavy pages, `--rendered` also writes a simple Markdown capture that is easier to review and reuse than raw HTML.

Outputs are written to:

- `output/markdown/<variant>.md`
- `output/pdf/<output_name>.pdf`
- `output/fetch/` for captured source pages

These generated files are intentionally ignored by git and can be reproduced by rerunning the commands above.

## How Tailoring Works

The renderer combines:

1. `data/profile.yaml`
2. `variants/<name>.yaml`

The profile keeps reusable facts. The variant file decides:

- which summary to use
- which experience entries to include
- which projects to include
- which skill groups to show
- whether to show selected publications or the full list
- whether to show selected patents or the full list
- which tool/framework groups to show separately from core skills

## Current Editing Flow

1. Update and clean `data/profile.yaml` with the goal of improving `complete`.
2. Re-render `complete` and review the Markdown/PDF outputs.
3. Once the complete version is clean, derive and tighten `short`.

## Notes

- The complete structured profile is seeded from `source/amir_harati_cv_v28_public.pdf`.
- Styled PDF generation uses Playwright with its own isolated Chromium runtime and does not use your installed Chrome profile.
- The renderer keeps a direct ReportLab fallback so PDF output still works if the isolated browser path is unavailable.
- `scripts/fetch_url.py` is the repo-local fallback for “grab this page/source first” tasks, including JS-heavy pages when run with `--rendered`.
