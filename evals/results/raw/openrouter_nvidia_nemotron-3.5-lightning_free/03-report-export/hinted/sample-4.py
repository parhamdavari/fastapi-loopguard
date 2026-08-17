python
   from fastapi import FastAPI
   import asyncio
   from pydantic import BaseModel
   import helpers

   app = FastAPI()

   class ReportRequest(BaseModel):
       rows: list

   @app.post("/reports")
   async def render_report(request: ReportRequest):
       rendered = await asyncio.to_thread(helpers.render_report, request.rows)
       return {"length": len(rendered)}
