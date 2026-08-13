from fastapi import FastAPI, Depends, Body, status
import asyncio

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges", status_code=status.HTTP_201_CREATED)
async def create_charge(
    amount: float = Body(..., embed=True),
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    receipt = await asyncio.to_thread(billing_client.charge, amount)
    return {"receipt": receipt}
