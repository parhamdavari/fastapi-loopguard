from fastapi import FastAPI, Depends, status
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


class ChargeResponse(BaseModel):
    receipt: str


@app.post("/charges", response_model=ChargeResponse, status_code=status.HTTP_201_CREATED)
async def create_charge(
    req: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    loop = asyncio.get_running_loop()
    # Run the synchronous billing_client.charge in a thread pool to avoid blocking the event loop
    receipt = await loop.run_in_executor(None, billing_client.charge, req.amount)
    return {"receipt": receipt}
