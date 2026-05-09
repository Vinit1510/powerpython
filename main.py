import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.server import app
from core.db import init_db, close_db
from worker.sync import worker_loop

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Startup: Initialize Neon Database and launch clock-synchronized background sync task
    await init_db()
    bg_task = asyncio.create_task(worker_loop())
    yield
    # Shutdown: Clean up connection pool and cancel background worker task
    print("[SYSTEM] Shutting down application...")
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    await close_db()

# Bind lifespan manager to our FastAPI application
app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"[SYSTEM] Starting VINIGEMI Python Suite on Port {port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
