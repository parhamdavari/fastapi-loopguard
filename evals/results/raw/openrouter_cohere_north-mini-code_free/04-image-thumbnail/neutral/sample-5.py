from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read the raw request body as bytes
    data = await request.body()
    
    # Produce the thumbnail using the provided helper
    thumbnail_bytes = helpers.resize_image(data)
    
    # Return the size of the thumbnail bytes
    return {"size": len(thumbnail_bytes)}
