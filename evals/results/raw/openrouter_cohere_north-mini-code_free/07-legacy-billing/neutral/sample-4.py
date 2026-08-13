from fastapi import FastAPI, Depends, Body

import helpers


app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(
    request: dict = Body(...),
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    receipt = billing_client.charge(request["amount"])
    return {"receipt": receipt}
