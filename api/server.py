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

                # 2. Fetch all real predictions for robust Python-based processing
                await cur.execute(
                    """
                    SELECT time_ist, size_win 
                    FROM predictions
                    WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%fallback%'
                    ORDER BY period_id DESC
                    """,
                    [game]
                )
                preds = await cur.fetchall()
                total_preds = len(preds)
                
                if total_preds > 0:
                    # A. Calculate Total Predicted & Won
                    total_won = sum(1 for p in preds if p[1] == "WIN")
                    analytics["totalPredicted"] = total_preds
                    analytics["totalWon"] = total_won
                    analytics["winRate"] = round((total_won / total_preds) * 100, 1)

                    # B. Calculate Last 10 Win Rate
                    l10_preds = preds[:10]
                    l10_total = len(l10_preds)
                    if l10_total > 0:
                        l10_won = sum(1 for p in l10_preds if p[1] == "WIN")
                        analytics["last10WinRate"] = round((l10_won / l10_total) * 100, 1)

                    # C. Calculate Last 20 Win Rate
                    l20_preds = preds[:20]
                    l20_total = len(l20_preds)
                    if l20_total > 0:
                        l20_won = sum(1 for p in l20_preds if p[1] == "WIN")
                        analytics["last20WinRate"] = round((l20_won / l20_total) * 100, 1)

                    # D. Calculate 10-Minute Blocks Win Rate safely in Python
                    block_counts = {0: {"total": 0, "wins": 0}, 1: {"total": 0, "wins": 0}, 2: {"total": 0, "wins": 0}, 3: {"total": 0, "wins": 0}, 4: {"total": 0, "wins": 0}, 5: {"total": 0, "wins": 0}}
                    for p in preds:
                        t_str, s_win = p[0], p[1]
                        try:
                            parts = t_str.split(":")
                            if len(parts) >= 2:
                                minute = int(parts[1])
                                block_idx = minute // 10
                                if 0 <= block_idx < 6:
                                    block_counts[block_idx]["total"] += 1
                                    if s_win == "WIN":
                                        block_counts[block_idx]["wins"] += 1
                        except Exception:
                            continue
                    
                    block_names = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60"]
                    for idx, stats in block_counts.items():
                        if stats["total"] > 0:
                            analytics["blocks"][block_names[idx]] = round((stats["wins"] / stats["total"]) * 100, 1)

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
