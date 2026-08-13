from fastapi import FastAPI, Depends, Body
import helpers
import asyncio

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def create_charge(
    amount: float = Body(...),
    billing_client: helpers.BillingClient = Depends(get_billing)
) -> dict:
    # Run the blocking charge call in a thread to avoid blocking the event loop
    receipt = await asyncio.to_thread(billing_client.charge, amount)
    return {"receipt": receipt}
