from fastapi import FastAPI, Depends

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(
    body: dict,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    amount = body["amount"]
    receipt = billing_client.charge(amount)
    return {"receipt": receipt}
