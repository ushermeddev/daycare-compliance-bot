import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from webhook import handle_line_event
from compliance_engine import run_compliance_check


@asynccontextmanager
async def lifespan(app: FastAPI):
    interval = int(os.getenv("COMPLIANCE_CHECK_INTERVAL_MINUTES", "10"))
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    scheduler.add_job(run_compliance_check, "interval", minutes=interval)
    scheduler.start()
    print(f"✅ 合規警示引擎啟動（每 {interval} 分鐘掃描）")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="托嬰合規助理",
    description="LINE-based compliance recording assistant for Taiwan day-care centers",
    version="1.0.0",
    lifespan=lifespan,
)

parser = WebhookParser(os.getenv("LINE_CHANNEL_SECRET", ""))


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid LINE signature")
    for event in events:
        asyncio.create_task(handle_line_event(event))
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "托嬰合規助理 v1.0"}


# ── Entry point (used by Railway via Procfile) ────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
