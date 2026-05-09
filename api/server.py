from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from core.db import pool
from worker.sync import state, sync_round

app = FastAPI(title="VINIGEMI Power-By-Python Engine")

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/stats")
async def get_stats(game: str = "1M"):
    """Fetch active prediction and recent 15 results from Neon PostgreSQL."""
    try:
        prediction = None
        if state["last_pred"]:
            prediction = {
                "number": state["last_pred"]["n"],
                "size": state["last_pred"]["sz"],
                "color": state["last_pred"]["col"],
                "method": state["last_pred"]["method"],
                "confidence": state["last_pred"]["confidence"],
                "targetId": state["last_pred"]["target_id"]
            }

        recent_rows = []
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT period_id, actual_num, actual_size, actual_color, pred_num, pred_size, pred_color, pattern_used, num_win, size_win, color_win, confidence
                    FROM predictions
                    WHERE game_type = %s
                    ORDER BY period_id DESC
                    LIMIT 15
                    """,
                    [game]
                )
                rows = await cur.fetchall()
                for r in rows:
                    recent_rows.append({
                        "periodId": r[0],
                        "actualNum": r[1],
                        "actualSize": r[2],
                        "actualColor": r[3],
                        "predNum": r[4],
                        "predSize": r[5],
                        "predColor": r[6],
                        "pattern": r[7],
                        "numWin": r[8],
                        "sizeWin": r[9],
                        "colorWin": r[10],
                        "confidence": r[11]
                    })
        return {"prediction": prediction, "recent": recent_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@app.post("/api/force-mine")
async def force_mine():
    """Manually trigger the sync loop and prediction check on demand."""
    try:
        print("[API] Manual force prediction check triggered...")
        success = await sync_round()
        return {
            "success": success,
            "message": "AI Prediction successfully mined!" if success else "Skip: No new period available on original API yet."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount Static frontend assets (dashboard index.html)
public_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
if os.path.exists(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
