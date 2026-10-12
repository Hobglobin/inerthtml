"""inerthtml: turn AI-generated HTML into a static, script-free file that is safe to share."""

__version__ = "0.1.0"

from .core import CSP, PROFILE, build, render, sanitize, verify  # noqa: E402

__all__ = ["CSP", "PROFILE", "build", "render", "sanitize", "verify", "__version__"]
