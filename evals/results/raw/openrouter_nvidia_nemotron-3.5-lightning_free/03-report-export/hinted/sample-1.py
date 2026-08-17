python
   from fastapi import FastAPI
   import asyncio
   import helpers

   app = FastAPI()

   class ReportRequest:
       rows: list

   # Actually, Pydantic model is better:
   from pydantic import BaseModel
   class ReportRequest(BaseModel):
       rows: list

   @app.post("/reports")
   async def render_report_endpoint(request: ReportRequest):
       rendered = await asyncio.to_thread(helpers.render_report, request.rows)
       return {"length": len(rendered)}
