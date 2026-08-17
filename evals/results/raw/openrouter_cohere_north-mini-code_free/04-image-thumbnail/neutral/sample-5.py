from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    # Read the raw request body
    data = await request.body()
    
    # Resize the image to create a thumbnail
    thumbnail = helpers.resize_image(data)
    
    # Return the size of the thumbnail
    return {"size": len(thumbnail)}
