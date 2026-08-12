from fastapi import FastAPI, Depends, status
from fastapi import Body
from fastapi.responses import JSONResponse

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(
    body: dict = Body(...),
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    amount = body.get("amount")
    if not isinstance(amount, (int, float)):
        return JSONResponse({"detail": "Invalid or missing 'amount'."}, status_code=400)

    receipt = billing_client.charge(float(amount))
    return {"receipt": receipt}
