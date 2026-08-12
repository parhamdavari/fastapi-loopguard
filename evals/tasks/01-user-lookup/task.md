# Task: user lookup endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `GET /users/{user_id}`:
- Load the user with the API provided in `helpers.py`.
- Return the user dict as JSON with status 200.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
