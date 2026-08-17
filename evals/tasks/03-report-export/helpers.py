"""Provided API. Do not modify."""

import time


def render_report(rows: list) -> str:
    """Render rows to a report. Synchronous and slow: ~150ms."""
    time.sleep(0.15)  # stands in for real CPU work
    return "\n".join(str(row) for row in rows)
