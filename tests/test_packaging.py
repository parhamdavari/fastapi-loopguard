"""Regression tests for release metadata.

Covers: __version__ drifting from pyproject.toml, and the 503 error page
linking to the wrong GitHub repository.
"""

import importlib.metadata
import pathlib
import tomllib

from starlette.types import Receive, Scope, Send

import fastapi_loopguard
from fastapi_loopguard import LoopGuardMiddleware
from fastapi_loopguard.context import RequestContext


async def _dummy_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Minimal ASGI app for constructing the middleware."""


def test_version_matches_installed_metadata() -> None:
    """__version__ must be derived from the installed package metadata."""
    assert fastapi_loopguard.__version__ == importlib.metadata.version(
        "fastapi-loopguard"
    )


def test_version_matches_pyproject() -> None:
    """__version__ must agree with pyproject.toml (no hand-written drift)."""
    pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert fastapi_loopguard.__version__ == data["project"]["version"]


def test_error_page_links_to_real_repo() -> None:
    """The 503 page must link to the repository that actually ships this code."""
    middleware = LoopGuardMiddleware(_dummy_app)
    ctx = RequestContext(request_id="abc12345", path="/x", method="GET")
    html = middleware._generate_error_html(ctx)
    assert "https://github.com/parhamdavari/fastapi-loopguard" in html
    assert "pyhub-kr" not in html
