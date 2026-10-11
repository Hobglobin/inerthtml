---
name: inert
description: Make an HTML file safe to share as a file. Use after creating an HTML report, dashboard or page that will be sent, attached, downloaded or shared outside a hosted link, or when asked to check whether an HTML file is safe to open.
---

# inert: share HTML as a safe, static file

`inert` turns an HTML page into one self-contained file that looks the same
but cannot run scripts, load anything from the network, or submit data. It
also checks any HTML file against those rules (the inert/1 profile).

## When creating HTML that will be shared

1. **Draw charts as SVG** so they stay vector after freezing:
   - D3, Plotly, Vega-Lite: SVG by default.
   - ECharts: `echarts.init(el, null, { renderer: 'svg' })`.
   - Chart.js only draws on canvas; it still works but becomes a PNG.
2. Keep interactivity in CSS where possible: `<details>`/`<summary>` for
   collapsible sections, `:target` or radio-button tabs. JavaScript won't
   survive.
3. Don't put forms, logins or embedded videos in a document meant to be shared.

## Build and verify

```bash
pip install inerthtml && playwright install chromium   # first time only
inert build report.html          # writes report.inert.html
inert verify report.inert.html   # must print PASS
```

- Charts that animate in: add `--wait 3000`.
- No browser available: `--no-render` (anything drawn by JS is lost; say so).
- Links not needed: `--strip-links`.

Share the `.inert.html` file, not the original. If `verify` fails, report the
listed problems; never hand over a file that failed.

## When asked "is this HTML file safe?"

Run `inert verify FILE` (it parses the file and never runs it) and explain
each problem in plain language, for example "it contains a form that sends
what you type to another site". A PASS means the file can't run code or send
data. It doesn't mean the text in it is true.
