**inerthtml** turns AI-generated HTML into one static file that is safe to share. It looks the same, opens in any browser and works offline, but it can't run scripts, load trackers or collect passwords. Anyone can check that with `inerthtml verify`.

![before and after](https://raw.githubusercontent.com/Hobglobin/inerthtml/main/assets/hero.png)

### Install

    pip install inerthtml
    playwright install chromium
    inerthtml build report.html

Or drop a file on the web checker: https://hobglobin.github.io/inerthtml/

### In this release

- `inerthtml build`: renders the page in headless Chromium, keeps SVG charts as vector and turns canvas charts into images, embeds CSS, fonts and images, strips anything active, and adds a strict Content Security Policy.
- `inerthtml verify`: checks any HTML file against the inert/1 rules without running it. `--json` for CI and mail filters.
- A browser checker on GitHub Pages: verify a file, preview it safely and download a cleaned copy. Nothing is uploaded.
- SPEC.md: the first draft of the inert/1 rules.
- A Claude skill in `skills/inerthtml` so agents produce shareable copies automatically.
- 63 tests, including parser-differential and CSS-escape bypass cases.

Found a way to make a file pass verify and still do something? Please report it privately (Security → Report a vulnerability). Bypasses are the most valuable bug reports this project can get.
