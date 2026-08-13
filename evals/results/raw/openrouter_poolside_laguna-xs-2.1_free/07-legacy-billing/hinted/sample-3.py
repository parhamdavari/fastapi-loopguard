import asyncio
from fastapi import FastAPI, Depends, status
from pydantic import BaseModel

import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    return billing


class ChargeRequest(BaseModel):
    amount: float


@app.post("/charges", status_code=status.HTTP_201_CREATED)
async def create_charge(
    charge_request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    receipt_id = await asyncio.to_thread(billing_client.charge, charge_request.amount)
    return {"receipt": receipt_id}
