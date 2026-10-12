---
name: inerthtml
description: Makes HTML safe to send as a file, and checks whether an HTML file is safe to open. Use whenever an HTML report, dashboard, chart page or document will be emailed, attached, sent, uploaded or shared as a file, even if the user doesn't ask for safety; build a static, script-free copy with `inerthtml build` and confirm it with `inerthtml verify` before handing it over. Also use whenever someone asks if an HTML file (an attachment, download or "shared document") is safe to open, might be phishing, or contains scripts or trackers; run `inerthtml verify` rather than only reading the source. Not needed for pages that stay on the user's machine or are served from a website.
---

# inerthtml: share HTML as a safe, static file

`inerthtml` turns an HTML page into one self-contained file that looks the same
but cannot run scripts, load anything from the network, or submit data. It
also checks any HTML file against those rules (the inert/1 profile).

The person you're helping may not be technical. Do the setup and the checks
yourself and tell them the result in plain words.

## Setup (once per session)

Run `inerthtml --version`. If the command isn't found, install it:

```bash
pip install inerthtml        # or: python3 -m pip install inerthtml, or: uv tool install inerthtml
```

A pip warning about running as root is harmless in a sandbox; carry on.

Do not upgrade or reinstall Playwright, and do not run `playwright install`.
Sandboxed environments often ship a Chromium that matches their Playwright
version, and changing either breaks it. If the browser is missing, use
`--no-render` (below) instead.

## When you write HTML that will be shared

1. **Draw charts as inline SVG** written straight into the HTML: `<rect>` bars,
   `<path>`/`<polyline>` lines, `<text>` labels and axes. Don't load chart
   libraries, fonts or anything else from a CDN. Sandboxes often block CDNs,
   and the chart would come out blank.
2. **No JavaScript.** Use CSS for interactivity: `<details>`/`<summary>` for
   collapsible sections, `:hover` for highlights, `:target` or radio-button tabs.
3. **No forms, logins or embedded videos.**
4. **Images:** embed them as `data:` URIs or keep them in local files next to the
   HTML. Use system fonts or local font files.

A page written this way needs no browser to clean it.

## Build and verify

- Page with no JavaScript (including pages you wrote as above):
  `inerthtml build page.html --no-render`
- Page that uses JavaScript (usually one the user gave you):
  1. First list every `<script src="http…">` it loads and check each host is
     reachable, for example `curl -sI -o /dev/null -w "%{http_code}" URL`
     (000 means blocked). If one isn't, the build will still pass but whatever
     that library draws (usually the charts) will be empty. Tell the user
     plainly and offer to redraw those charts as inline SVG from the numbers in
     the page's script, then build the redrawn page with `--no-render`.
  2. Otherwise run `inerthtml build page.html`. This renders it in headless
     Chromium so charts drawn by scripts are kept. If the build fails because
     the browser can't start, run it again with `--no-render` and tell the user
     that anything drawn by scripts (usually charts) could not be kept.
- Then run `inerthtml verify page.inert.html`. It must print PASS. Never hand
  over a file that failed; tell the user what's wrong instead.

Useful options: `-o OUT` to name the output, `--wait 3000` for charts that
animate in, `--strip-links` when links aren't needed. Warnings that a remote
asset couldn't be fetched are expected when the network is restricted; mention
it only if something visible is missing.

Save the finished `.inert.html` file wherever this environment makes files
downloadable for the user (for example an outputs folder), and point them to it.

## Telling the user

In one to three plain sentences:

- which file to send (the `.inert.html` copy, not the original);
- that it opens in any browser, works offline, and can't run scripts, track the
  reader or collect what they type;
- anything that was removed or couldn't be kept (a form, a tracking pixel, a
  chart drawn by scripts).

Don't show commands or tool output unless they ask.

## When asked whether an HTML file is safe to open

Run `inerthtml verify FILE`. It reads the file and never runs it. Explain each
problem plainly, for example "it has a login form that sends your password to
another website" or "it loads a hidden image that tells the sender you opened
it". A PASS means the file can't run code or send data. It doesn't mean the text
in it is true. If they still need to see the content, offer a cleaned copy made
with `inerthtml build FILE --no-render`.
