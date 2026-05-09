from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import core.db
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
        analytics = {
            "totalPredicted": 0,
            "totalWon": 0,
            "winRate": 0.0,
            "last10WinRate": 0.0,
            "last20WinRate": 0.0,
            "blocks": {
                "0-10": 0.0,
                "10-20": 0.0,
                "20-30": 0.0,
                "30-40": 0.0,
                "40-50": 0.0,
                "50-60": 0.0
            }
        }

        async with core.db.pool.connection() as conn:
            async with conn.cursor() as cur:
                # 1. Fetch recent results
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

                # 2. Calculate Total Predicted & Won
                await cur.execute(
                    """
                    SELECT COUNT(*), SUM(CASE WHEN size_win = 'WIN' THEN 1 ELSE 0 END)
                    FROM predictions
                    WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%fallback%'
                    """,
                    [game]
                )
                total_row = await cur.fetchone()
                if total_row and total_row[0] > 0:
                    analytics["totalPredicted"] = total_row[0]
                    analytics["totalWon"] = total_row[1] or 0
                    analytics["winRate"] = round((analytics["totalWon"] / analytics["totalPredicted"]) * 100, 1)

                # 3. Calculate Last 10 Win Rate
                await cur.execute(
                    """
                    SELECT COUNT(*), SUM(CASE WHEN size_win = 'WIN' THEN 1 ELSE 0 END)
                    FROM (
                        SELECT size_win FROM predictions
                        WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%fallback%'
                        ORDER BY period_id DESC LIMIT 10
                    ) t
                    """,
                    [game]
                )
                l10_row = await cur.fetchone()
                if l10_row and l10_row[0] > 0:
                    analytics["last10WinRate"] = round(((l10_row[1] or 0) / l10_row[0]) * 100, 1)

                # 4. Calculate Last 20 Win Rate
                await cur.execute(
                    """
                    SELECT COUNT(*), SUM(CASE WHEN size_win = 'WIN' THEN 1 ELSE 0 END)
                    FROM (
                        SELECT size_win FROM predictions
                        WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%fallback%'
                        ORDER BY period_id DESC LIMIT 20
                    ) t
                    """,
                    [game]
                )
                l20_row = await cur.fetchone()
                if l20_row and l20_row[0] > 0:
                    analytics["last20WinRate"] = round(((l20_row[1] or 0) / l20_row[0]) * 100, 1)

                # 5. Calculate 10-Minute Blocks Win Rate
                await cur.execute(
                    """
                    SELECT 
                        CAST(SPLIT_PART(time_ist, ':', 2) AS INTEGER) / 10 AS block,
                        COUNT(*),
                        SUM(CASE WHEN size_win = 'WIN' THEN 1 ELSE 0 END)
                    FROM predictions
                    WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%fallback%'
                    GROUP BY block
                    ORDER BY block
                    """,
                    [game]
                )
                block_rows = await cur.fetchall()
                block_names = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60"]
                for b_r in block_rows:
                    b_idx = int(b_r[0])
                    if 0 <= b_idx < 6:
                        b_total = b_r[1]
                        b_wins = b_r[2] or 0
                        analytics["blocks"][block_names[b_idx]] = round((b_wins / b_total) * 100, 1)

        return {"prediction": prediction, "recent": recent_rows, "analytics": analytics}
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
