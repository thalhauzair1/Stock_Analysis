import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

import state
from api.routes import router
from database import init_db
from scheduler import _run_job, create_scheduler
from utils.logger import get_logger

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Initialising database …")
    init_db()

    logger.info("Starting background scheduler …")
    scheduler = create_scheduler()
    scheduler.start()

    # Run one analysis immediately so the API has data on first request
    logger.info("Running initial analysis (this may take ~60 s) …")
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_job)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped. Goodbye.")


app = FastAPI(
    title="Stock Intelligence Multi-Agent System",
    description=(
        "Signal aggregation and ranking system that identifies high-probability "
        "stock setups using momentum, volume, technicals, VWAP, breakouts, "
        "news sentiment, and smart-money signals."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

# ── Dashboard (static HTML) ───────────────────────────────────────────────────
_DASHBOARD = Path("dashboard") / "index.html"

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    if _DASHBOARD.exists():
        return FileResponse(_DASHBOARD)
    return HTMLResponse("<h2>Dashboard not found. Make sure dashboard/index.html exists.</h2>")


# ── Dev entry-point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
