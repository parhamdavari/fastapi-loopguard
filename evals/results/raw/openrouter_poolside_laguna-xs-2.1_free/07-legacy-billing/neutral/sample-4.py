from fastapi import FastAPI, Body, Depends
import helpers

app = FastAPI()

billing = helpers.BillingClient()

def get_billing() -> helpers.BillingClient:
    return billing

@app.post("/charges", status_code=201)
def create_charge(
    amount: float = Body(...),
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    receipt = billing_client.charge(amount)
    return {"receipt": receipt}
