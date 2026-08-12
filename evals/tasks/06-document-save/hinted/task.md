# Task: document save endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /documents` accepting `{"name": "<name>", "text": "<text>"}`:
- Persist the document with `helpers.save_document(name, text)`.
- Return `{"bytes": <the helper's return value>}` with status 201.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
