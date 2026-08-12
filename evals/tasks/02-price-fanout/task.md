# Task: portfolio price fan-out

Complete `app_skeleton.py` (save your result as `app.py`).

Implement `GET /portfolio?symbols=AAA,BBB,CCC`:
- Fetch the price of every symbol with the API in `helpers.py`.
- Fetch them concurrently: total latency must stay close to one fetch,
  not the sum of all fetches.
- Return `{"prices": {symbol: price, ...}}` with status 200.

Constraints:
- The endpoint must not block the event loop.
- Use only `helpers.py` and the standard library.
