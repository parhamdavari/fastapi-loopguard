from fastapi import FastAPI, Depends, Body

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(
    amount: float = Body(..., embed=True),
    billing: helpers.BillingClient = Depends(get_billing),
):
    receipt = billing.charge(amount)
    return {"receipt": receipt}
