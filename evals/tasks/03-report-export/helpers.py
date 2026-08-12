"""Provided API. Do not modify."""

import time


def render_report(rows: list) -> str:
    """Render rows to a report. CPU-bound: ~150ms, holds the GIL."""
    time.sleep(0.15)  # stands in for real CPU work
    return "\n".join(str(row) for row in rows)
