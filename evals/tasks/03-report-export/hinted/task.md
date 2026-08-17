# Task: report rendering endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /reports` accepting `{"rows": [...]}`:
- Render the report with `helpers.render_report(rows)`.
- Return `{"length": <len of rendered string>}` with status 200.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
