from fastapi import FastAPI, Depends
import asyncio
import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def create_charge(amount: float, billing: helpers.BillingClient = Depends(get_billing)):
    # Offload the blocking synchronous charge call to a thread to avoid blocking the event loop
    receipt = await asyncio.to_thread(billing.charge, amount)
    return {"receipt": receipt}
