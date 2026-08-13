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
    billing: helpers.BillingClient = Depends(get_billing)
):
    """Charge the amount and return a receipt."""
    amount = body["amount"]
    receipt = billing.charge(amount)
    return {"receipt": receipt}
