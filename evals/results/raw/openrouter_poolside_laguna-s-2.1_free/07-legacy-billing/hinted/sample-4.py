from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


@app.post("/charges")
async def create_charge(request: ChargeRequest, client: helpers.BillingClient = Depends(get_billing)):
    loop = asyncio.get_event_loop()
    receipt = await loop.run_in_executor(None, client.charge, request.amount)
    return JSONResponse({"receipt": receipt}, status_code=201)
