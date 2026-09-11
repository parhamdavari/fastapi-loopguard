"""The fix hints have one definition, and every surface renders that one.

These hints are instructions a coding agent follows literally (see
docs/AI-HARNESS.md), so they are checked for content as well as for
consistency: a hint that names an undeclared package makes the agent add a
dependency the README deliberately avoids.
"""

from __future__ import annotations

import html
import json

from starlette.types import Receive, Scope, Send

from fastapi_loopguard.context import RequestContext
from fastapi_loopguard.hints import FIX_HINTS, hint_lines
from fastapi_loopguard.middleware import LoopGuardMiddleware, _format_console_warning


async def _noop_app(scope: Scope, receive: Receive, send: Send) -> None:
    """An ASGI app that does nothing; the renderers never call it."""
    return None


def _ctx() -> RequestContext:
    ctx = RequestContext(request_id="deadbeef", path="/api/users", method="GET")
    ctx.record_blocking(3000.1)
    return ctx


class TestFixHints:
    """The list itself."""

    def test_hint_lines_render_the_table(self) -> None:
        assert hint_lines() == [
            f"{before} -> {after}" for _, before, after in FIX_HINTS
        ]

    def test_no_hint_names_an_undeclared_package(self) -> None:
        """aiofiles was recommended here once.

        It is third-party, declared in no extra, and the printed form
        (`await aiofiles.open(f)`) is not how the library is used. Only the
        standard library and httpx -- which the README already recommends
        and the dev extra installs -- may appear.
        """
        rewrites = " ".join(after for _, _, after in FIX_HINTS)
        for package in ("aiofiles", "aiohttp", "aiopath", "openai", "requests"):
            assert package not in rewrites

    def test_http_hint_closes_its_client(self) -> None:
        """`await httpx.AsyncClient().get(url)` leaked a client per call."""
        assert hint_lines()[1] == (
            "requests.get(url) -> async with httpx.AsyncClient() as client: "
            "await client.get(url)"
        )

    def test_file_hint_uses_the_standard_library(self) -> None:
        assert hint_lines()[2] == (
            "open(path).read() -> await asyncio.to_thread(Path(path).read_text)"
        )

    def test_subprocess_hint_waits_for_the_process(self) -> None:
        assert hint_lines()[3] == (
            "subprocess.run(cmd) -> proc = await "
            "asyncio.create_subprocess_exec(*cmd); await proc.wait()"
        )


class TestEverySurfaceRendersTheSameList:
    """Banner, 503 JSON and 503 HTML all read fastapi_loopguard.hints."""

    def test_console_banner(self) -> None:
        text = _format_console_warning(_ctx(), use_color=False)
        for _, before, after in FIX_HINTS:
            assert f"    {before}\n      -> {after}" in text

    def test_banner_fits_an_eighty_column_terminal(self) -> None:
        text = _format_console_warning(_ctx(), use_color=False)
        assert max(len(line) for line in text.split("\n")) <= 80

    def test_strict_mode_json_body(self) -> None:
        middleware = LoopGuardMiddleware(app=_noop_app)
        body = json.loads(middleware._generate_error_json(_ctx()))
        assert body["help"]["common_causes"] == hint_lines()

    def test_strict_mode_html_page(self) -> None:
        middleware = LoopGuardMiddleware(app=_noop_app)
        page = middleware._generate_error_html(_ctx())
        for label, before, after in FIX_HINTS:
            assert f"# {html.escape(label)}" in page
            assert html.escape(before) in page
            assert html.escape(after) in page
        assert "aiofiles" not in page
