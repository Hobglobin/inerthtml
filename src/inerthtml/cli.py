"""Command line interface: `inerthtml build` and `inerthtml verify`."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.parse

from . import __version__
from .core import build, to_url, verify

EPILOG = """examples:
  inerthtml build report.html                  # -> report.inert.html
  inerthtml build report.html -o shared.html --width 1200 --wait 3000
  inerthtml build https://example.com/page -o page.inert.html
  inerthtml build report.html --no-render      # sanitize only, no browser
  inerthtml verify report.inert.html           # exit code 1 if it fails
  inerthtml verify *.html --json               # machine-readable results
"""


def _default_output(source: str) -> pathlib.Path:
    url = to_url(source)
    if url.startswith("file:"):
        p = pathlib.Path(urllib.parse.unquote(urllib.parse.urlparse(url).path))
        stem = p.name[:-5] if p.name.endswith(".html") else p.stem
        return p.with_name(f"{stem}.inert.html")
    host = urllib.parse.urlparse(url).netloc.replace(":", "_") or "page"
    return pathlib.Path(f"{host}.inert.html")


def cmd_build(args) -> int:
    if args.output and len(args.inputs) > 1:
        print("error: -o/--output works with a single input; use --out-dir", file=sys.stderr)
        return 2
    status = 0
    for src in args.inputs:
        out_html, warnings, problems = build(
            src, render_page=not args.no_render, width=args.width, wait_ms=args.wait,
            scale=args.scale, strip_links=args.strip_links, offline=args.offline)
        out = pathlib.Path(args.output) if args.output else _default_output(src)
        if args.out_dir:
            out = pathlib.Path(args.out_dir) / out.name
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(out_html, "utf-8")
        for w in warnings:
            print(f"  warning: {w}", file=sys.stderr)
        size = out.stat().st_size / 1024
        try:
            out = out.resolve().relative_to(pathlib.Path.cwd())
        except ValueError:
            pass
        if problems:
            status = 1
            print(f"✗ {out} ({size:.0f} KB) built, but verify FAILED:")
            for p in problems:
                print(f"    - {p}")
        else:
            print(f"✓ {out} ({size:.0f} KB) inert, verify PASS")
    return status


def cmd_verify(args) -> int:
    results = {}
    for f in args.files:
        try:
            results[f] = verify(pathlib.Path(f).read_text("utf-8", "replace"))
        except OSError as e:
            results[f] = [f"cannot read file: {e}"]
    if args.json:
        print(json.dumps({f: {"pass": not p, "problems": p} for f, p in results.items()},
                         indent=2))
    else:
        for f, problems in results.items():
            if problems:
                print(f"✗ FAIL  {f}")
                for p in problems:
                    print(f"    - {p}")
            else:
                print(f"✓ PASS  {f}")
    return 1 if any(results.values()) else 0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog="inerthtml",
        description="Turn HTML into a static, script-free file that is safe to share.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"inerthtml {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="render, freeze and sanitize HTML into an inert file")
    b.add_argument("inputs", nargs="+", help="HTML file path(s) or http(s) URL(s)")
    b.add_argument("-o", "--output", help="output file (single input only)")
    b.add_argument("--out-dir", help="directory for outputs")
    b.add_argument("--width", type=int, default=1280, help="render width in px (default 1280)")
    b.add_argument("--wait", type=int, default=2000,
                   help="ms to wait for charts/animations after load (default 2000)")
    b.add_argument("--scale", type=float, default=2,
                   help="pixel density for canvas->PNG (default 2)")
    b.add_argument("--no-render", action="store_true",
                   help="skip the browser; sanitize the HTML as written")
    b.add_argument("--strip-links", action="store_true",
                   help="remove all hyperlinks (keep their text)")
    b.add_argument("--offline", action="store_true",
                   help="never fetch remote assets (local files only)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="check files against the inert/1 rules")
    v.add_argument("files", nargs="+")
    v.add_argument("--json", action="store_true", help="print JSON results")
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
