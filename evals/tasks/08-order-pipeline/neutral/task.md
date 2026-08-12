# Task: order processing endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `POST /orders` accepting `{"item": "<name>"}`:
- Process the order with `helpers.process_order(order)`, passing the request
  body as the order.
- Return the processed order dict with status 201.

Constraints:
- Use only `helpers.py` and the standard library.
