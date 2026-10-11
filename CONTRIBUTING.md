# Contributing

Thanks for helping. inert is small on purpose, and a few rules keep it that way.

## Setup

```bash
git clone https://github.com/YOUR_GITHUB/inert && cd inert
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest
```

## Ground rules

- **Two implementations, one behaviour.** The Python package
  (`src/inerthtml/core.py`) and the web checker (`docs/inert.js`) must agree.
  `tests/test_inert.py::test_js_and_python_agree` enforces this. If you change
  a rule in one, change it in both.
- **Every bypass gets a test.** Add the payload to the parametrized tests
  before fixing it.
- **Rule changes need a spec change.** If a fix changes what passes or fails,
  update [SPEC.md](SPEC.md) in the same pull request.
- **Prefer removing to rewriting.** When unsure whether something is safe,
  drop it.

## Good first issues

- More chart-library examples in `examples/` (Plotly, Vega-Lite, Mermaid)
- Font subsetting to shrink embedded Google Fonts
- A Node port of the CLI (`npx inert`)
