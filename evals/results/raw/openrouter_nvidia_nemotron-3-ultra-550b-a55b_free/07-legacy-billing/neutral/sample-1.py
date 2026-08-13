from fastapi import FastAPI, Depends, status
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
def create_charge(
    request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    receipt = billing_client.charge(request.amount)
    return {"receipt": receipt}
