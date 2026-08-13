from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
import asyncio

import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


@app.post("/charges", status_code=201)
async def create_charge(request: ChargeRequest):
    loop = asyncio.get_event_loop()
    receipt = await loop.run_in_executor(
        None, billing.charge, request.amount
    )
    return {"receipt": receipt}
