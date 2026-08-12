from fastapi import FastAPI, Depends, status
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncio

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float = Field(...)


@app.post("/charges", status_code=status.HTTP_201_CREATED)
async def create_charge(
    req: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    loop = asyncio.get_running_loop()
    # Call the blocking .charge in a thread pool executor
    receipt = await loop.run_in_executor(
        None, billing_client.charge, req.amount
    )
    return {"receipt": receipt}
