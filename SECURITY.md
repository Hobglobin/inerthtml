# Security

inerthtml is a security tool, so bypasses are the most valuable bugs you can find.

## What counts as a vulnerability

- A file that **passes `inerthtml verify`** (Python or the web checker) but can
  run script, load a network resource, submit data, or navigate on its own
  in a current browser.
- `inerthtml build` producing output that does any of the above, even if
  `verify` catches it.
- The web checker running code from a file it was given.

Content problems (a passing file that *says* something misleading) are out of
scope; see "What it does not protect against" in [SPEC.md](SPEC.md#7-security-considerations).

## Reporting

Please report privately using GitHub's **"Report a vulnerability"** button
(Security → Advisories) on this repository. Include a minimal HTML file and
the browser and version you tested.

We aim to reply within 7 days. Fixed bypasses get a regression test in
`tests/` and a credit in the changelog, unless you prefer to stay anonymous.
