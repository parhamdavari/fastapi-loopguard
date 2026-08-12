# Task: payment charge endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /charges` accepting `{"amount": <number>}`:
- Charge the amount through the billing client wired into the skeleton.
- Return `{"receipt": "<receipt id>"}` with status 201.

Constraints:
- Use only `helpers.py` and the standard library.
