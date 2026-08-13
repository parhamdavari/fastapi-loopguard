from fastapi import FastAPI, Depends, status
from pydantic import BaseModel
import asyncio

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
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    # Offload the synchronous blocking call to a thread pool
    receipt = await asyncio.to_thread(billing_client.charge, request.amount)
    return {"receipt": receipt}
