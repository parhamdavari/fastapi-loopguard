# Task: CPU-bound report rendering

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /reports` accepting `{"rows": [...]}`:
- Render the report with `helpers.render_report(rows)`.
- Return `{"length": <len of rendered string>}` with status 200.

Note: `helpers.py` has no async variant this time - rendering is
CPU-bound. Keeping the event loop free is still your responsibility.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
