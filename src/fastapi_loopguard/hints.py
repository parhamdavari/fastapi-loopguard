"""The suggested rewrites LoopGuard reports, defined once.

Every surface that tells a human or an agent what to write instead reads
this list: the console banner, the strict-mode 503 page and JSON body, and
the ``hints`` array the pytest plugin writes into its report. ``README.md``
quotes it and is kept in sync by hand -- there is no generation step.

Layering: this module imports nothing at all, so it sits below every layer
in CLAUDE.md's map. ``middleware`` (on the detection path) and
``pytest_plugin`` (a leaf that must not import ``middleware``) can both
read it without inverting the dependency order.

Content rule: a hint may only name the standard library or a package this
project already documents for its users (``httpx``). ``aiofiles`` used to
be here -- third-party, declared nowhere, and printed in a form
(``await aiofiles.open(f)``) that is not how the library is used. Each
replacement below is a complete, working expression on its own.
"""

# (category, blocking call, the async rewrite). The category labels the
# pair on the strict-mode error page; the other surfaces render
# "blocking -> rewrite".
FIX_HINTS: tuple[tuple[str, str, str], ...] = (
    ("Sleeping", "time.sleep(n)", "await asyncio.sleep(n)"),
    (
        "HTTP requests",
        "requests.get(url)",
        "async with httpx.AsyncClient() as client: await client.get(url)",
    ),
    (
        "File I/O",
        "open(path).read()",
        "await asyncio.to_thread(Path(path).read_text)",
    ),
    (
        "Subprocess",
        "subprocess.run(cmd)",
        "proc = await asyncio.create_subprocess_exec(*cmd); await proc.wait()",
    ),
    (
        "CPU-bound work",
        "tokenizer.encode(text)",
        "await asyncio.to_thread(tokenizer.encode, text)",
    ),
)


def hint_lines() -> list[str]:
    """One ``blocking call -> async rewrite`` string per hint."""
    return [f"{before} -> {after}" for _, before, after in FIX_HINTS]
