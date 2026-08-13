from fastapi import Body, Depends

import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
def create_charge(
    amount: float = Body(..., embed=True),
    client: helpers.BillingClient = Depends(get_billing),
):
    receipt = client.charge(amount)
    return {"receipt": receipt}
