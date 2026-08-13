from fastapi import FastAPI, Body, Depends

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def charge_endpoint(
    payload: dict = Body(..., example={"amount": 10.0}),
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    """Create a new charge and return receipt."""
    amount = payload["amount"]
    receipt = billing_client.charge(amount)
    return {"receipt": receipt}
