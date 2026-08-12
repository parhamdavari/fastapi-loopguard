from fastapi import FastAPI, Body
import asyncio
import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=201)
async def create_charge(amount: float = Body(...)):
    receipt = await asyncio.to_thread(billing.charge, amount)
    return {"receipt": receipt}
