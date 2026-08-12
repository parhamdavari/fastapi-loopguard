from fastapi import FastAPI, Body
import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(amount: float = Body(...)):
    receipt_id = billing.charge(amount)
    return {"receipt": receipt_id}
