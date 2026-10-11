# The inert/1 profile

**Status:** draft, version 1 · **Editors:** the inert contributors · **License:** CC-BY 4.0

An *inert HTML document* is an ordinary HTML file that any browser can open,
but that cannot run code, load anything from the network, or send anything
anywhere. It is meant for documents: reports, dashboards, write-ups and
AI-generated pages that people want to share as a file.

This document lists the rules. A file that follows them **passes**; anything
else **fails**. `inert verify` (Python) and `docs/inert.js` (browser) are
reference checkers.

The key words MUST, MUST NOT and MAY are used as described in RFC 2119.

## 1. Design goals

1. **Opens anywhere.** No special viewer. Any modern browser renders it.
2. **Checkable without trust.** Anyone can decide pass/fail by reading the
   file, without running it, and without trusting the sender or the tool
   that made it.
3. **Defence in depth.** The markup rules remove active content, and a
   Content Security Policy makes the browser refuse it anyway.
4. **Faithful look.** HTML and CSS are kept, including layout, CSS-only
   interactivity (`<details>`, `:hover`, `:target`) and inline SVG.

Non-goals: confidentiality, authorship, or proof that the content is true.
inert/1 says what a file *can do*, not who wrote it. Signing is out of scope
for version 1 (see §7).

## 2. Document structure

1. The file MUST be a single HTML document encoded as UTF-8.
2. `<head>` MUST start with a `<meta http-equiv="Content-Security-Policy">`
   element. The only element allowed before it is `<meta charset>`.
3. The policy MUST contain, at least:
   - `default-src 'none'`
   - `form-action 'none'`
   - and MUST NOT allow scripts: if `script-src` is present it MUST be
     exactly `script-src 'none'`.
4. Every source listed in any directive MUST be one of `'none'`, `data:`
   or `'unsafe-inline'`, and `'unsafe-inline'` MAY appear only in
   `style-src`. No host, scheme (other than `data:`), `'self'`,
   `'unsafe-eval'`, nonce or hash is allowed.
5. The recommended policy is:

   ```
   default-src 'none'; script-src 'none'; object-src 'none';
   style-src 'unsafe-inline'; img-src data:; font-src data:;
   media-src 'none'; frame-src 'none'; connect-src 'none';
   form-action 'none'; base-uri 'none'
   ```

6. A document SHOULD declare `<meta name="inert-profile" content="inert/1">`.
   Checkers MUST NOT rely on it: a file passes or fails by its content.

## 3. Forbidden elements

The document MUST NOT contain any of these elements, in HTML, SVG or MathML:

`script`, `noscript`, `template`, `iframe`, `frame`, `frameset`,
`fencedframe`, `portal`, `object`, `embed`, `applet`, `base`, `link`,
`form`, `video`, `audio`, `source`, `track`, `foreignObject`.

Also forbidden:

- `<meta http-equiv>` with any value other than `Content-Security-Policy`
  (this covers `refresh` redirects and `set-cookie`).
- `<input type="password">` and `<input type="file">`.
- SVG animation elements (`set`, `animate`, `animateTransform`,
  `animateMotion`) whose `attributeName` is `href` or `xlink:href`.

Other form controls (`input`, `button`, `select`, `textarea`) MAY appear for
display. Without `<form>`, scripts or `form-action` they cannot send data.
Generators SHOULD mark them `disabled`.

## 4. Forbidden attributes

1. No attribute whose name starts with `on` (event handlers).
2. None of: `action`, `formaction`, `srcdoc`, `srcset`, `imagesrcset`,
   `ping`, `poster`, `background`, `data`, `cite`, `longdesc`, `manifest`,
   `codebase`, `archive`.

## 5. URLs

### 5.1 Links (navigation)

`href` on `<a>` (HTML or SVG), and any other `href`/`xlink:href` that is not
a resource reference (§5.2), MUST be one of:

- a fragment (`#section`)
- a relative URL
- an absolute URL with scheme `http:`, `https:`, `mailto:` or `tel:`

Any other scheme is forbidden, including `javascript:`, `data:`, `vbscript:`,
`file:` and `blob:`. Before checking, remove ASCII whitespace and control
characters and lowercase the value (so `java\tscript:` is caught).

Generators SHOULD add `rel="noopener noreferrer nofollow"` and
`target="_blank"`, and SHOULD set `title` to the destination so readers can
see where a link goes.

### 5.2 Embedded resources

`src` (on any element) and `href`/`xlink:href` on SVG `<image>`, `<feImage>`
and `<use>` are resource references:

- On `<use>`, the value MUST be a fragment (`#id`).
- Everywhere else the value MUST be a `data:` URI whose media type starts
  with `image/`, `font/`, `application/font`, `application/x-font`,
  `application/vnd.ms-fontobject` or `application/octet-stream`.

`data:image/svg+xml` is allowed: browsers never run scripts in SVG loaded as
an image.

### 5.3 CSS

This applies to `<style>` contents, `style` attributes, and any other
attribute whose value contains `url(` (for example SVG `fill`, `filter`,
`mask`, `clip-path`, `marker-*`):

- No `@import`.
- Every `url(...)` MUST be a fragment (`url(#gradient)`) or an allowed
  `data:` URI (§5.2). `@namespace` URLs are exempt because they are never
  fetched.
- Every quoted string inside `image-set(...)` MUST be an allowed `data:` URI.
- No `expression(`, `-moz-binding`, `behavior:` or `javascript:`.

## 6. Conformance

- **A checker** MUST report a failure for every rule above that a document
  breaks, and MUST NOT execute the document while checking. It SHOULD parse
  with an HTML5-conformant parser (or one at least as strict).
- **A generator** MUST only output documents that pass, and SHOULD run a
  checker on its own output.
- **A viewer or gateway** MAY treat a passing document as non-executable
  content. It SHOULD still open it in a sandboxed context when possible
  (for example `<iframe sandbox>` with no flags).

## 7. Security considerations

- **What inert/1 protects against:** running code (including HTML smuggling),
  collecting and sending input, tracking pixels and other network beacons,
  automatic redirects, and loading remote content that could change after
  the file was checked.
- **What it does not protect against:** the *content itself*. An inert file
  can still say "call this number" or show a link to a phishing site. Links
  are allowed (§5.1) so that documents can cite sources. Use
  `inert build --strip-links` when links aren't needed.
- **Tampering:** anyone can edit an inert file. Editing it to add active
  content makes it fail verification, so receivers should verify, not trust.
  Proof of authorship (signatures) is planned for a later profile.
- **Parser differences:** checkers built on different parsers can disagree
  on malformed markup. A future version may require generators to emit
  documents that round-trip through an HTML5 parser unchanged.
- **CSP via `<meta>`:** browsers apply a meta CSP only to content after the
  element, which is why §2 requires it to come first. It cannot set
  `frame-ancestors`, `sandbox` or `report-uri`; none are needed here.

## 8. Changes

- **inert/1** (2026): first draft.
