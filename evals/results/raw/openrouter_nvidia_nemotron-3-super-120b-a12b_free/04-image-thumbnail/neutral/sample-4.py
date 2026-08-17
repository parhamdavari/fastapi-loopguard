We are to implement a POST endpoint at `/thumbnail` that accepts raw image bytes in the request body.
 Steps:
 1. We are given that `helpers.resize_image(data)` takes bytes and returns a thumbnail (also bytes).
 2. We need to return a JSON object: {"size": <length of the thumbnail bytes>} with status 200.

 Since the endpoint accepts raw request body, we can use `Request` to get the body as bytes.

 However, note: In FastAPI, to get the raw body we can use:
   - `body: bytes = Body(...)` but that would expect a specific media type? Actually, for raw bytes we can use `Request` and then `await request.body()`.

 Alternatively, we can define the endpoint to accept `bytes` directly? But note: the request body is raw image bytes, not JSON.

 According to FastAPI docs, for raw bytes we can do:

   @app.post("/thumbnail")
   async def thumbnail(request: Request):
        data = await request.body()
        thumbnail_data = helpers.resize_image(data)
        return {"size": len(thumbnail_data)}

 However, note that the problem says: "accepting a raw request body of image bytes".

 But wait: the skeleton does not import Request. We have to import it.

 Alternatively, we can use:

   from fastapi import FastAPI, Request

 But note: the constraints say to use only helpers.py and the standard library. However, FastAPI is allowed because it's in the skeleton.

 However, the skeleton already imports FastAPI. We are allowed to add imports from fastapi? The problem says "Use only `helpers.py` and the standard library." but note that the skeleton already uses FastAPI. So we are allowed to use FastAPI and its components.

 But note: the problem says "Complete `app_skeleton.py`", meaning we can add necessary imports.

 However, let's read the constraints again: "Use only `helpers.py` and the standard library." - but wait, the skeleton already imports FastAPI and helpers. So we are allowed to use FastAPI? Actually, the problem says we are to complete the skeleton which already has FastAPI.

 Since the skeleton already imports FastAPI, we can assume that we are allowed to use FastAPI. But note: the constraint says "Use only helpers.py and the standard library", which might be interpreted as we cannot use any other third-party libraries. However, the skeleton already uses FastAPI (which is third-party). So I think the constraint means: besides the given helpers and the standard library, we cannot use any other third-party libraries. But FastAPI is already given in the skeleton, so we can use it.

 Alternatively, the constraint might be about the helpers module: we are only allowed to use helpers.py (which is provided) and the standard library for our implementation. But note that we are building on top of FastAPI which is already imported.

 Let me clarify: the skeleton has:
   from fastapi import FastAPI
   import helpers

 So we are allowed to use FastAPI and helpers.

 Therefore, we can do:

   from fastapi import Request   # but wait, we already have FastAPI imported, so we can import Request from fastapi?

 However, note: we can also get the body without importing Request by using a different method? Actually, no: to get the raw body we need the Request object.

 Alternatively, we can use:

   @app.post("/thumbnail")
   async def thumbnail(data: bytes = Body(...)):
        ...

 But wait: the Body(...) expects the body to be sent as raw bytes? Actually, by default, FastAPI expects JSON. To accept raw bytes, we have to set the media type or use Request.

 According to the documentation: 
   To receive raw bytes, you can define the parameter as `bytes` and use `Body(...)` but then you must set the media type to something like `application/octet-stream`? However, the problem says "raw request body", meaning the client will send the image as the raw body without any wrapping.

 Actually, in FastAPI, if you define a parameter as `bytes` and use `Body(...)`, it will read the body as raw bytes. But note: the documentation says that for large files it's better to use UploadFile, but here we are getting raw bytes.

 Example from docs: 
   https://fastapi.tiangolo.com/tutorial/request-files/#request-files-as-uploadfile
   But also: 
   https://fastapi.tiangolo.com/tutorial/request-forms/#request-form-data

 However, for raw bytes without any form, we can do:

   @app.post("/thumbnail")
   async def thumbnail(file: bytes = Body(...)):
        ...

 But note: the Body(...) by default expects the content type to be 'application/json'. To accept arbitrary bytes, we have to set the media type? Actually, no: if we don't specify, FastAPI will try to decode as JSON. So we have to avoid that.

 Alternatively, we can use:

   @app.post("/thumbnail")
   async def thumbnail(request: Request):
        data = await request.body()
        ...

 This is the standard way to get raw bytes.

 Since the problem says "raw request body", we'll use the Request method.

 Steps in code:
   1. Import Request from fastapi (if not already imported). We have to add this import.
   2. Define the endpoint as a POST route at "/thumbnail".
   3. In the endpoint function, get the raw body by awaiting request.body().
   4. Pass that data to helpers.resize_image.
   5. Return a dictionary with key "size" and value being the length of the thumbnail bytes.

 However, note: the helpers.resize_image function is CPU-bound and takes about 150ms (simulated by time.sleep). We are making it async? But note: the function is blocking. However, since we are in an async endpoint, we should avoid blocking the event loop.

 But the problem does not specify that we must use async/await for the helpers function. However, if we call a blocking function in an async endpoint, it will block the event loop.

 We have two options:
   a) Make the endpoint synchronous (remove async) and then call the blocking function. But then we lose the ability to handle multiple requests concurrently? However, for a CPU-bound task, we might want to use threads or processes. But the problem does not specify performance requirements beyond the given.

   b) Use run_in_threadpool to run the blocking function in a thread pool.

 However, note: the problem says "Use only helpers.py and the standard library". We are allowed to use asyncio? Since it's standard library.

 But the skeleton does not use async anywhere else. And the problem does not specify whether we should use async or sync.

 Let's look at the skeleton: it doesn't specify async for any endpoint. We are free to choose.

 However, the helpers.resize_image function is blocking (because of time.sleep). If we make the endpoint async and call the blocking function directly, it will block the event loop.

 Since the problem does not specify concurrency requirements, and to keep it simple, we can make the endpoint synchronous? But note: the skeleton uses FastAPI which is async by default. We can define a synchronous endpoint and FastAPI will run it in a thread pool? Actually, no: by default, if you define a normal function (not async) in FastAPI, it will run in the threadpool for handling the request? Actually, FastAPI will run synchronous endpoint functions in an external threadpool to avoid blocking the main event loop.

 But wait: the documentation says:
   "If your path operation function is defined with `def` instead of `async def`, it will be ran in an external threadpool."

 So we can define the endpoint as a normal function (without async) and then the blocking call to helpers.resize_image will be run in a threadpool, which is acceptable.

 Alternatively, we can define it as async and then use `run_in_threadpool` from `fastapi.concurrency` to run the blocking function. But that would require an import.

 However, the problem says to use only helpers.py and the standard library. We are allowed to use FastAPI, but we are not supposed to use any other third-party? But note: `fastapi.concurrency` is part of FastAPI.

 But let's stick to the simplest: define the endpoint as a synchronous function.

 Steps:

   from fastapi import FastAPI, Request
   import helpers

   app = FastAPI()

   @app.post("/thumbnail")
   def thumbnail(request: Request):
        data = await request.body()   # Wait, but if the function is not async, we cannot use await.

 So if we define the function as `def`, we cannot use `await`. Therefore, we have two choices:

   Option 1: Make the endpoint async and then use `await request.body()` and then call the blocking function directly (which will block the event loop). This is not ideal for performance but acceptable for low traffic or if we don't care about blocking.

   Option 2: Make the endpoint sync and then use `request.body()` without await? But note: in a sync function, how do we get the body? Actually, the Request object in a sync function has a `.body()` method that is synchronous? Let me check the FastAPI documentation.

   Actually, the Request object has a `.body()` method that returns the body as bytes, and it is synchronous? But note: the body might be large and reading it might be blocking. However, the body is already read by the server? 

   Looking at the source: in Starlette (which FastAPI is built on), the `request.body()` method is a coroutine? Actually, no: in the Request class, the `
