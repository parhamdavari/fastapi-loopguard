from fastapi import FastAPI, Depends, Body
from pydantic import BaseModel

import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


@app.post("/charges", status_code=201)
async def create_charge(
    request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    receipt = billing_client.charge(request.amount)
    return {"receipt": receipt}
