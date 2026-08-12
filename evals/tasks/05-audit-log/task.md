# Task: order creation with audit trail

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /orders` accepting `{"item": "<name>"}`:
- Append an audit line `"order:<name>"` using the API in `helpers.py`.
- Return `{"status": "created"}` with status 201.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
