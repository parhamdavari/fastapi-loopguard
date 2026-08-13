from fastapi import FastAPI, Depends, Body
import asyncio
import helpers

app = FastAPI()

billing = helpers.BillingClient()


def get_billing() -> helpers.BillingClient:
    return billing


@app.post("/charges", status_code=201)
async def create_charge(
    amount: float = Body(..., embed=True),
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    receipt = await asyncio.to_thread(billing_client.charge, amount)
    return {"receipt": receipt}
