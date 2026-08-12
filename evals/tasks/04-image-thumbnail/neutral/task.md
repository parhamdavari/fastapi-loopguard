# Task: image thumbnail endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /thumbnail` accepting a raw request body of image bytes:
- Produce a thumbnail with `helpers.resize_image(data)`.
- Return `{"size": <len of thumbnail bytes>}` with status 200.

Constraints:
- Use only `helpers.py`, FastAPI's `Request`, and the standard library.
