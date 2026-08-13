from fastapi import FastAPI, Depends, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


@app.post("/charges", status_code=status.HTTP_201_CREATED)
async def create_charge(
    request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
) -> dict[str, str]:
    receipt = await run_in_threadpool(billing_client.charge, request.amount)
    return {"receipt": receipt}
