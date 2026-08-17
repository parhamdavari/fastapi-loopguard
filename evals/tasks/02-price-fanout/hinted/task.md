# Task: portfolio price endpoint

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `GET /portfolio?symbols=AAA,BBB,CCC`:
- Fetch the price of every symbol with the API in `helpers.py`.
- Return `{"prices": {symbol: price, ...}}` with status 200.
- A request for three symbols must complete in under 0.3 seconds.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
