from typing import Annotated

from fastapi import Depends, FastAPI

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def charge(
    payload: dict, client: Annotated[helpers.BillingClient, Depends(get_billing)]
) -> dict:
    receipt = client.charge(payload["amount"])  # blocks ~120ms
    return {"receipt": receipt}
