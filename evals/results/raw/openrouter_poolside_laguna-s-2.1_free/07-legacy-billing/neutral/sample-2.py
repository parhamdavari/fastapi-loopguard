from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float = Field(..., gt=0)


class ChargeResponse(BaseModel):
    receipt: str


@app.post("/charges", response_model=ChargeResponse, status_code=201)
def create_charge(
    payload: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    receipt_id = billing_client.charge(payload.amount)
    return ChargeResponse(receipt=receipt_id)
