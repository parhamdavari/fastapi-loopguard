from fastapi import FastAPI, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest(BaseModel):
    amount: float


class ReceiptResponse(BaseModel):
    receipt: str


@app.post("/charges", response_model=ReceiptResponse, status_code=status.HTTP_201_CREATED)
def create_charge(
    charge: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    receipt_id = billing_client.charge(charge.amount)
    return {"receipt": receipt_id}
