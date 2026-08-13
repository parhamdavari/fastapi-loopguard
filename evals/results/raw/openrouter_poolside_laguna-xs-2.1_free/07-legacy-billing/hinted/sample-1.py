from fastapi import FastAPI, Depends
import asyncio
from pydantic import BaseModel

import helpers

app = FastAPI()

billing = helpers.BillingClient()

def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing

class ChargeRequest(BaseModel):
    amount: float

@app.post("/charges")
async def charge_endpoint(
    request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    loop = asyncio.get_running_loop()
    receipt = await loop.run_in_executor(
        None, billing_client.charge, request.amount
    )
    return {"receipt": receipt}, 201
