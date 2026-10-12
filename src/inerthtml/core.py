"""
Core of inerthtml: render -> freeze -> inline -> sanitize -> verify.

An *inert HTML* file is a single, self-contained HTML document that a normal
browser displays exactly as written, but that cannot run code, load anything
from the network, or send anything anywhere. See SPEC.md for the rules.
"""

from __future__ import annotations

import base64
import mimetypes
import pathlib
import re
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup, Comment
from bs4.element import Stylesheet

from . import __version__

PROFILE = "inert/1"

CSP = ("default-src 'none'; script-src 'none'; object-src 'none'; "
       "style-src 'unsafe-inline'; img-src data:; font-src data:; "
       "media-src 'none'; frame-src 'none'; connect-src 'none'; "
       "form-action 'none'; base-uri 'none'")

# Zero-specificity helper CSS so frozen charts scale down on small screens.
HELPER_CSS = (":where(svg[data-inert-chart]),:where(img[data-inert-frozen])"
              "{max-width:100%;height:auto}")

FORBIDDEN_TAGS = {
    "script", "noscript", "iframe", "frame", "frameset", "object", "embed",
    "applet", "base", "portal", "template", "video", "audio", "source",
    "track", "foreignobject", "fencedframe", "link", "form",
}
URL_ATTRS = {"href", "xlink:href", "src", "poster", "background", "action",
             "formaction", "data", "cite", "longdesc", "ping", "srcset",
             "imagesrcset", "srcdoc", "manifest", "codebase", "archive"}
DROP_ATTRS = URL_ATTRS - {"href", "xlink:href", "src"}
SAFE_LINK_SCHEMES = ("http:", "https:", "mailto:", "tel:")
SAFE_DATA_PREFIXES = ("data:image/", "data:font/", "data:application/font",
                      "data:application/x-font", "data:application/octet-stream",
                      "data:application/vnd.ms-fontobject")
ANIM_TAGS = {"set", "animate", "animatetransform", "animatemotion"}

BAD_CSS = re.compile(r"expression\s*\(|-moz-binding|behavior\s*:|javascript:", re.I)
CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)""", re.I)
CSS_IMPORT = re.compile(
    r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]+)["']?\s*\)?\s*([^;]*?)\s*(?:;|$)""", re.I)
CSS_IMPORT_ANY = re.compile(r"@import[^;]*;?", re.I)
CSS_NAMESPACE = re.compile(r"@namespace[^;]*;", re.I)
CSS_IMAGE_SET = re.compile(r"image-set\(([^)]*)\)", re.I)
CSS_QUOTED = re.compile(r"""["']([^"']*)["']""")

CSS_ESCAPE = re.compile(r"\\([0-9a-fA-F]{1,6})[ \t\n\r\f]?|\\([^\n\r\f0-9a-fA-F])")
CSS_PLAIN = re.compile(r"[A-Za-z0-9:/().@_\-]")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_ASSET = 15 * 1024 * 1024


# ----------------------------------------------------------------- helpers

def css_unescape(css: str) -> str:
    """Decode CSS escapes that spell identifier/URL characters, so that
    u\\72l( or @\\69mport can't hide from the checks. Other escapes (e.g.
    quotes inside strings, typographic characters) are left alone."""
    def repl(m):
        if m.group(1):
            try:
                c = chr(int(m.group(1), 16))
            except (ValueError, OverflowError):
                return m.group(0)
        else:
            c = m.group(2)
        return c if CSS_PLAIN.fullmatch(c) else m.group(0)
    return CSS_ESCAPE.sub(repl, css)


def _norm(value: str) -> str:
    return re.sub(r"[\s\x00-\x1f]", "", value).lower()


def _attr_ci(tag, name: str) -> str:
    """Attribute value by case-insensitive name (SVG keeps camelCase)."""
    for k, v in tag.attrs.items():
        if str(k).lower() == name:
            return " ".join(v) if isinstance(v, list) else str(v)
    return ""


def is_safe_data_uri(value: str) -> bool:
    return _norm(value).startswith(SAFE_DATA_PREFIXES)


def is_link_attr(tag_name: str, attr: str) -> bool:
    """href on <a> (HTML or SVG) and other navigational hrefs."""
    return tag_name == "a" or (attr != "src" and tag_name not in ("image", "use", "feimage"))


def to_url(src: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*://", src, re.I):
        return src
    return pathlib.Path(src).resolve().as_uri()


# ----------------------------------------------------------------- render

FREEZE_JS = r"""
async () => {
  try { await document.fonts.ready; } catch (e) {}

  // <canvas> -> high-DPI PNG <img>
  for (const c of Array.from(document.querySelectorAll('canvas'))) {
    let url = null;
    try { url = c.toDataURL('image/png'); } catch (e) {}
    const r = c.getBoundingClientRect();
    const img = document.createElement('img');
    for (const a of ['id', 'class', 'style']) {
      if (c.hasAttribute(a)) img.setAttribute(a, c.getAttribute(a));
    }
    if (url) img.src = url;
    img.alt = c.getAttribute('aria-label') || c.getAttribute('title') || 'chart';
    img.style.width = r.width + 'px';
    img.style.height = 'auto';
    img.setAttribute('data-inert-frozen', 'canvas');
    c.replaceWith(img);
  }

  // Top-level <svg>: give it a viewBox so it can scale; mark charts.
  for (const s of Array.from(document.querySelectorAll('svg'))) {
    if (s.parentElement && s.parentElement.closest('svg')) continue;
    const r = s.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (!s.hasAttribute('viewBox')) {
      s.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
      if (!s.hasAttribute('width')) s.setAttribute('width', r.width);
      if (!s.hasAttribute('height')) s.setAttribute('height', r.height);
    }
    if (r.width >= 150 && r.height >= 80) s.setAttribute('data-inert-chart', '');
  }

  // Bake current form state into attributes.
  for (const el of Array.from(document.querySelectorAll('input'))) {
    const t = (el.type || '').toLowerCase();
    if (t === 'checkbox' || t === 'radio') {
      el.checked ? el.setAttribute('checked', '') : el.removeAttribute('checked');
    } else if (t !== 'password' && t !== 'file') {
      el.setAttribute('value', el.value);
    }
  }
  for (const el of Array.from(document.querySelectorAll('textarea'))) el.textContent = el.value;
  for (const el of Array.from(document.querySelectorAll('select option'))) {
    el.selected ? el.setAttribute('selected', '') : el.removeAttribute('selected');
  }

  // CSS-in-JS: rules inserted via CSSOM don't appear in textContent.
  const rulesText = (sheet) => {
    try { return Array.from(sheet.cssRules).map(r => r.cssText).join('\n'); }
    catch (e) { return ''; }
  };
  for (const st of Array.from(document.querySelectorAll('style'))) {
    if (st.sheet && !st.textContent.trim()) st.textContent = rulesText(st.sheet);
  }
  for (const sheet of (document.adoptedStyleSheets || [])) {
    const st = document.createElement('style');
    st.textContent = rulesText(sheet);
    document.head.appendChild(st);
  }

  return '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
}
"""


def render(url: str, width: int = 1280, wait_ms: int = 2000, scale: float = 2):
    """Load a page in headless Chromium, let it draw, return (frozen_html, final_url)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Rendering needs Playwright: pip install playwright && "
                         "playwright install chromium (or use --no-render)") from e
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            if "Executable doesn't exist" in str(e):
                raise SystemExit("Chromium for Playwright is missing. Run once:\n"
                                 "    playwright install chromium\n"
                                 "(or use --no-render to skip the browser)") from None
            raise
        ctx = browser.new_context(viewport={"width": width, "height": 900},
                                  device_scale_factor=scale, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)          # let chart animations finish
        html = page.evaluate(FREEZE_JS)
        final_url = page.url
        browser.close()
    return html, final_url


def read_source(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


# ----------------------------------------------------------------- inlining

class Fetcher:
    def __init__(self, offline: bool = False):
        self.cache: dict = {}
        self.warnings: list[str] = []
        self.offline = offline

    def get(self, url: str):
        if url in self.cache:
            return self.cache[url]
        result = None
        if self.offline and not url.startswith("file:"):
            self.warnings.append(f"offline: not fetching {url}")
            self.cache[url] = None
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read(MAX_ASSET + 1)
                ctype = r.headers.get_content_type() if url.startswith("http") else None
            if len(data) > MAX_ASSET:
                self.warnings.append(f"skipped (larger than 15 MB): {url}")
            else:
                if not ctype or ctype in ("application/octet-stream", "text/plain"):
                    ctype = (mimetypes.guess_type(urllib.parse.urlparse(url).path)[0]
                             or ctype or "application/octet-stream")
                result = (data, ctype)
        except Exception as e:  # noqa: BLE001
            self.warnings.append(f"could not fetch {url}: {e}")
        self.cache[url] = result
        return result

    def data_uri(self, url: str):
        got = self.get(url)
        if not got:
            return None
        data, ctype = got
        uri_prefix = f"data:{ctype}"
        if not uri_prefix.startswith(SAFE_DATA_PREFIXES):
            self.warnings.append(f"dropped non-image/font asset: {url} ({ctype})")
            return None
        return f"{uri_prefix};base64,{base64.b64encode(data).decode()}"


def inline_css(css: str, base: str, fetch: Fetcher, depth: int = 0) -> str:
    """Inline @imports and url()s; neutralise dangerous constructs."""
    css = css_unescape(css)
    def do_import(m):
        if depth > 5:
            return ""
        url = urllib.parse.urljoin(base, m.group(1))
        got = fetch.get(url)
        if not got:
            return ""
        inner = inline_css(got[0].decode("utf-8", "replace"), url, fetch, depth + 1)
        media = m.group(2).strip()
        return f"@media {media}{{{inner}}}" if media else inner

    css = CSS_IMPORT.sub(do_import, css)
    css = CSS_IMPORT_ANY.sub("", css)                # anything malformed
    namespaces = CSS_NAMESPACE.findall(css)          # not fetched; keep verbatim
    css = CSS_NAMESPACE.sub("", css)

    def do_url(m):
        ref = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not ref or ref.startswith("#"):          # SVG gradient/clip refs
            return m.group(0)
        if ref.lower().startswith("data:"):
            return m.group(0) if is_safe_data_uri(ref) else "none"
        uri = fetch.data_uri(urllib.parse.urljoin(base, ref))
        return f'url("{uri}")' if uri else "none"

    css = CSS_URL.sub(do_url, css)

    def do_image_set(m):
        inner = CSS_QUOTED.sub(
            lambda q: q.group(0) if is_safe_data_uri(q.group(1)) else '""', m.group(1))
        return f"image-set({inner})"

    css = CSS_IMAGE_SET.sub(do_image_set, css)
    css = BAD_CSS.sub("/*removed*/", css)
    return "".join(namespaces) + css


# ----------------------------------------------------------------- sanitize

def safe_link(href: str, base: str, base_is_web: bool):
    h = href.strip()
    if not h:
        return None
    if h.startswith("#"):
        return h
    low = _norm(h)
    if low.startswith(SAFE_LINK_SCHEMES):
        return h
    if re.match(r"^[a-z][a-z0-9+.-]*:", low):      # javascript:, data:, file:...
        return None
    if base_is_web:                                  # relative web link
        return urllib.parse.urljoin(base, h)
    return None                                      # relative local file link


def sanitize(html: str, base: str = "about:blank", strip_links: bool = False,
             offline: bool = False):
    """Turn (already rendered) HTML into an inert document. Returns (html, warnings)."""
    fetch = Fetcher(offline=offline)
    soup = BeautifulSoup(html, "html5lib")
    base_is_web = base.startswith(("http:", "https:"))

    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()

    for t in soup.find_all(lambda t: t.name.lower() in ANIM_TAGS):
        if _norm(_attr_ci(t, "attributename")) in ("href", "xlink:href"):
            t.decompose()

    for t in soup.find_all("meta"):
        if t.get("http-equiv") is not None or t.get("charset") is not None:
            t.decompose()

    # <link rel=stylesheet> -> inlined <style>; every other <link> goes.
    for t in soup.find_all("link"):
        rel = t.get("rel") or []
        rel = " ".join(rel) if isinstance(rel, list) else rel
        if "stylesheet" in rel.lower() and t.get("href"):
            url = urllib.parse.urljoin(base, t["href"])
            got = fetch.get(url)
            if got:
                style = soup.new_tag("style")
                if t.get("media"):
                    style["media"] = t["media"]
                style.append(Stylesheet(
                    inline_css(got[0].decode("utf-8", "replace"), url, fetch)))
                t.replace_with(style)
                continue
        t.decompose()

    # Forms: keep the look, remove the ability to collect or send anything.
    for t in soup.find_all("form"):
        t.name = "div"
        t["data-inert-form"] = ""

    for t in soup.find_all(lambda t: t.name.lower() in FORBIDDEN_TAGS):
        t.decompose()

    for t in soup.find_all("style"):
        css = inline_css(t.string or "", base, fetch)
        t.clear()
        t.append(Stylesheet(css))

    for t in soup.find_all("input"):
        if (t.get("type") or "").lower() in ("password", "file", "hidden", "image"):
            t.decompose()
        else:
            t["disabled"] = ""
    for t in soup.find_all(["textarea", "select"]):
        t["disabled"] = ""
    for t in soup.find_all("button"):
        t["type"] = "button"
    for t in soup.find_all("picture"):
        t.unwrap()

    for t in soup.find_all(True):
        name = t.name.lower()
        for attr in list(t.attrs):
            a = attr.lower()
            val = t.attrs[attr]
            sval = " ".join(val) if isinstance(val, list) else str(val)
            if a.startswith("on") or a in DROP_ATTRS:
                del t.attrs[attr]
            elif a == "style":
                t.attrs[attr] = inline_css(sval, base, fetch)
            elif a in ("src", "href", "xlink:href"):
                if is_link_attr(name, a):
                    fixed = safe_link(sval, base, base_is_web)
                    if fixed is None or strip_links:
                        del t.attrs[attr]
                    else:
                        t.attrs[attr] = fixed
                elif name == "use":
                    if not sval.strip().startswith("#"):
                        del t.attrs[attr]
                elif sval.strip().lower().startswith("data:"):
                    if not is_safe_data_uri(sval):
                        del t.attrs[attr]
                else:  # <img src>, SVG <image>/<feImage> href -> inline it
                    uri = fetch.data_uri(urllib.parse.urljoin(base, sval))
                    if uri:
                        t.attrs[attr] = uri
                    else:
                        del t.attrs[attr]
            elif "url(" in css_unescape(sval).lower() and _bad_urls(sval):
                del t.attrs[attr]          # e.g. SVG fill="url(https://...)"
        if name == "a":
            if t.get("href"):
                t["rel"] = "noopener noreferrer nofollow"
                t["target"] = "_blank"
                if not t.get("title"):
                    t["title"] = t["href"]      # show the real destination
            elif "target" in t.attrs:
                del t.attrs["target"]

    # Make sure there is <html><head>.
    if not soup.html:
        wrapper = BeautifulSoup("<!DOCTYPE html><html><head></head><body></body></html>",
                                "html.parser")
        for child in list(soup.contents):
            if getattr(child, "name", None) or str(child).strip():
                wrapper.body.append(child.extract())
        soup = wrapper
    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        soup.html.insert(0, head)

    helper = soup.new_tag("style")
    helper.append(Stylesheet(HELPER_CSS))
    for node in reversed([
        soup.new_tag("meta", attrs={"charset": "utf-8"}),
        soup.new_tag("meta", attrs={"http-equiv": "Content-Security-Policy", "content": CSP}),
        soup.new_tag("meta", attrs={"name": "inert-profile", "content": PROFILE}),
        soup.new_tag("meta", attrs={"name": "generator", "content": f"inerthtml {__version__}"}),
        helper,
    ]):
        head.insert(0, node)

    out = str(soup)
    out = re.sub(r"^\s*(<!DOCTYPE[^>]*>\s*)?", "<!DOCTYPE html>\n", out, count=1, flags=re.I)
    return out, fetch.warnings


def build(source: str, *, render_page: bool = True, width: int = 1280,
          wait_ms: int = 2000, scale: float = 2, strip_links: bool = False,
          offline: bool = False):
    """File path or URL -> (inert_html, warnings, problems)."""
    url = to_url(source)
    if render_page:
        html, base = render(url, width, wait_ms, scale)
    else:
        html, base = read_source(url), url
    out, warnings = sanitize(html, base, strip_links, offline)
    return out, warnings, verify(out)


# ----------------------------------------------------------------- verify

def _bad_urls(css: str) -> list[str]:
    css = CSS_NAMESPACE.sub("", css_unescape(css))
    bad = []
    for m in CSS_URL.finditer(css):
        ref = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if ref and not ref.startswith("#") and not is_safe_data_uri(ref):
            bad.append(ref)
    for m in CSS_IMAGE_SET.finditer(css):
        for q in CSS_QUOTED.finditer(m.group(1)):
            if q.group(1) and not is_safe_data_uri(q.group(1)):
                bad.append(q.group(1))
    return bad


def _check_css(css: str, where: str) -> list[str]:
    css = css_unescape(css)
    out = []
    if BAD_CSS.search(css):
        out.append(f"dangerous CSS in {where}")
    if re.search(r"@import", css, re.I):
        out.append(f"@import in {where}")
    for ref in _bad_urls(css):
        out.append(f"external url() in {where}: {ref[:60]}")
    return out


def verify(html: str) -> list[str]:
    """Check a document against the inert/1 rules. Empty list == PASS."""
    soup = BeautifulSoup(html, "html5lib")
    problems: list[str] = []

    head = soup.head
    csp = soup.find("meta", attrs={"http-equiv": re.compile(r"^\s*content-security-policy\s*$", re.I)})
    before = []
    if head and csp:
        for el in head.find_all(True, recursive=False):
            if el is csp:
                break
            before.append(el)
    if not csp or csp.parent is not head or any(
            not (el.name == "meta" and el.has_attr("charset")) for el in before):
        problems.append("missing CSP <meta> at the top of <head>")
    else:
        pol = " ".join(csp.get("content", "").split())
        directives = {d.strip().split(" ")[0].lower(): d.strip()
                      for d in pol.split(";") if d.strip()}
        if directives.get("default-src") != "default-src 'none'":
            problems.append("CSP must contain default-src 'none'")
        if directives.get("script-src", "script-src 'none'") != "script-src 'none'":
            problems.append("CSP must not allow scripts")
        if directives.get("form-action") != "form-action 'none'":
            problems.append("CSP must contain form-action 'none'")
        for d, text in directives.items():
            srcs = text.split(" ")[1:]
            if any(s not in ("'none'", "'unsafe-inline'", "data:") for s in srcs):
                problems.append(f"CSP directive allows remote sources: {text}")
            if "'unsafe-inline'" in srcs and d != "style-src":
                problems.append(f"CSP allows inline content outside styles: {text}")

    for t in soup.find_all(True):
        name = t.name.lower()
        if name in FORBIDDEN_TAGS:
            problems.append(f"forbidden element <{name}>")
        if name == "meta" and t.get("http-equiv") and \
                t.get("http-equiv").strip().lower() != "content-security-policy":
            problems.append(f"forbidden <meta http-equiv={t.get('http-equiv')}>")
        if name == "input" and (t.get("type") or "").lower() in ("password", "file"):
            problems.append(f"forbidden <input type={t.get('type')}>")
        if name in ANIM_TAGS and _norm(_attr_ci(t, "attributename")) in ("href", "xlink:href"):
            problems.append(f"<{name}> animates a link target")
        for attr, val in t.attrs.items():
            a = attr.lower()
            sval = " ".join(val) if isinstance(val, list) else str(val)
            low = _norm(sval)
            if a.startswith("on"):
                problems.append(f"event handler {a} on <{name}>")
            elif a in ("src", "href", "xlink:href"):
                if is_link_attr(name, a):
                    if re.match(r"^[a-z][a-z0-9+.-]*:", low) and \
                            not low.startswith(SAFE_LINK_SCHEMES):
                        problems.append(f"unsafe link on <{name}>: {sval[:60]}")
                elif name == "use":
                    if not low.startswith("#"):
                        problems.append("<use> references an external resource")
                elif not is_safe_data_uri(sval):
                    problems.append(f"external resource on <{name}>: {sval[:60]}")
            elif a in URL_ATTRS:
                problems.append(f"forbidden attribute {a} on <{name}>")
            elif a == "style":
                problems += _check_css(sval, f"style attribute on <{name}>")
            elif "url(" in css_unescape(sval).lower():
                problems += [f"external url() in {a} on <{name}>: {r[:60]}"
                             for r in _bad_urls(sval)]
        if name == "style":
            problems += _check_css(t.string or "", "<style>")
    return sorted(set(problems))
