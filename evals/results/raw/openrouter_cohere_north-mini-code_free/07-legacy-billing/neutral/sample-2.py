from fastapi import FastAPI, Request, Depends
import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def charge_endpoint(
    request: Request,
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    data = await request.json()
    amount = data["amount"]
    receipt_id = billing_client.charge(amount)
    return {"receipt": receipt_id}
