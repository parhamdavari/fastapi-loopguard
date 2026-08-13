from fastapi import FastAPI, Body, Depends, status
import asyncio
import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


class ChargeRequest:
    def __init__(self, amount: float = Body(..., embed=True)):
        self.amount = amount


@app.post("/charges", status_code=status.HTTP_201_CREATED)
async def create_charge(
    request: ChargeRequest,
    billing_client: helpers.BillingClient = Depends(get_billing)
):
    loop = asyncio.get_event_loop()
    receipt = await loop.run_in_executor(None, billing_client.charge, request.amount)
    return {"receipt": receipt}
