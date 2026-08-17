python
from fastapi import FastAPI, Depends

import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges")
def create_charge(
    billing_client: helpers.BillingClient = Depends(get_billing),
    amount: float
):
    receipt = billing_client.charge(amount)
    return {"receipt": receipt}, 201
