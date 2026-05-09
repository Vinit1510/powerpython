from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import io
import csv
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
            "sizeWins": 0,
            "colorWins": 0,
            "sizeWinRate": 0.0,
            "colorWinRate": 0.0,
            "last10SizeWinRate": 0.0,
            "last10ColorWinRate": 0.0,
            "last20SizeWinRate": 0.0,
            "last20ColorWinRate": 0.0,
            "blocks": {
                "0-10": {"size": 0.0, "color": 0.0},
                "10-20": {"size": 0.0, "color": 0.0},
                "20-30": {"size": 0.0, "color": 0.0},
                "30-40": {"size": 0.0, "color": 0.0},
                "40-50": {"size": 0.0, "color": 0.0},
                "50-60": {"size": 0.0, "color": 0.0}
            },
            "hourly": {}
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
                    SELECT time_ist, size_win, color_win 
                    FROM predictions
                    WHERE game_type = %s AND LOWER(pattern_used) NOT LIKE '%%fallback%%'
                    ORDER BY period_id DESC
                    """,
                    [game]
                )
                preds = await cur.fetchall()
                total_preds = len(preds)
                
                if total_preds > 0:
                    # A. Calculate Total Predicted & Won
                    size_won = sum(1 for p in preds if p[1] == "WIN")
                    color_won = sum(1 for p in preds if p[2] == "WIN")
                    analytics["totalPredicted"] = total_preds
                    analytics["sizeWins"] = size_won
                    analytics["colorWins"] = color_won
                    analytics["sizeWinRate"] = round((size_won / total_preds) * 100, 1)
                    analytics["colorWinRate"] = round((color_won / total_preds) * 100, 1)

                    # B. Calculate Last 10 Win Rate
                    l10_preds = preds[:10]
                    l10_total = len(l10_preds)
                    if l10_total > 0:
                        l10_size_won = sum(1 for p in l10_preds if p[1] == "WIN")
                        l10_color_won = sum(1 for p in l10_preds if p[2] == "WIN")
                        analytics["last10SizeWinRate"] = round((l10_size_won / l10_total) * 100, 1)
                        analytics["last10ColorWinRate"] = round((l10_color_won / l10_total) * 100, 1)

                    # C. Calculate Last 20 Win Rate
                    l20_preds = preds[:20]
                    l20_total = len(l20_preds)
                    if l20_total > 0:
                        l20_size_won = sum(1 for p in l20_preds if p[1] == "WIN")
                        l20_color_won = sum(1 for p in l20_preds if p[2] == "WIN")
                        analytics["last20SizeWinRate"] = round((l20_size_won / l20_total) * 100, 1)
                        analytics["last20ColorWinRate"] = round((l20_color_won / l20_total) * 100, 1)

                    # D. Calculate 10-Minute Blocks Win Rate safely in Python
                    block_counts = {0: {"total": 0, "size_wins": 0, "color_wins": 0}, 1: {"total": 0, "size_wins": 0, "color_wins": 0}, 2: {"total": 0, "size_wins": 0, "color_wins": 0}, 3: {"total": 0, "size_wins": 0, "color_wins": 0}, 4: {"total": 0, "size_wins": 0, "color_wins": 0}, 5: {"total": 0, "size_wins": 0, "color_wins": 0}}
                    for p in preds:
                        t_str, s_win, c_win = p[0], p[1], p[2]
                        try:
                            if t_str and ":" in t_str:
                                parts = t_str.split(":")
                                if len(parts) >= 2:
                                    minute = int(parts[1])
                                    block_idx = minute // 10
                                    if 0 <= block_idx < 6:
                                        block_counts[block_idx]["total"] += 1
                                        if s_win == "WIN":
                                            block_counts[block_idx]["size_wins"] += 1
                                        if c_win == "WIN":
                                            block_counts[block_idx]["color_wins"] += 1
                        except Exception:
                            continue
                    
                    block_names = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60"]
                    for idx, stats in block_counts.items():
                        if stats["total"] > 0:
                            analytics["blocks"][block_names[idx]]["size"] = round((stats["size_wins"] / stats["total"]) * 100, 1)
                            analytics["blocks"][block_names[idx]]["color"] = round((stats["color_wins"] / stats["total"]) * 100, 1)

                    # E. Calculate Hourwise Win Rate safely in Python
                    hourly_counts = {h: {"total": 0, "size_wins": 0, "color_wins": 0} for h in range(24)}
                    for p in preds:
                        t_str, s_win, c_win = p[0], p[1], p[2]
                        try:
                            if t_str and ":" in t_str:
                                parts = t_str.split(":")
                                hour = int(parts[0])
                                if 0 <= hour < 24:
                                    hourly_counts[hour]["total"] += 1
                                    if s_win == "WIN":
                                        hourly_counts[hour]["size_wins"] += 1
                                    if c_win == "WIN":
                                        hourly_counts[hour]["color_wins"] += 1
                        except Exception:
                            continue
                    
                    for hour, stats in hourly_counts.items():
                        if stats["total"] > 0:
                            h_label = f"{str(hour).zfill(2)}:00 - {str(hour+1).zfill(2)}:00"
                            analytics["hourly"][h_label] = {
                                "size": round((stats["size_wins"] / stats["total"]) * 100, 1),
                                "color": round((stats["color_wins"] / stats["total"]) * 100, 1)
                            }

        return {"prediction": prediction, "recent": recent_rows, "analytics": analytics}
    except Exception as e:
        import traceback
        print("[API ERROR] Failed in /api/stats:")
        traceback.print_exc()
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

@app.get("/api/export")
async def export_data():
    """Export predictions history database as an Excel-compatible CSV file."""
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Period ID", "Actual Number", "Actual Size", "Actual Color", "Predicted Number", "Predicted Size", "Predicted Color", "Strategy Used", "Size Result", "Color Result", "Date (IST)", "Time (IST)"])
        
        async with core.db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT period_id, actual_num, actual_size, actual_color, pred_num, pred_size, pred_color, pattern_used, size_win, color_win, date_ist, time_ist
                    FROM predictions
                    ORDER BY period_id DESC
                    """
                )
                rows = await cur.fetchall()
                for r in rows:
                    writer.writerow(r)
        
        output.seek(0)
        return StreamingResponse(
            io.StringIO(output.getvalue()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=vinigemi_predictor_history.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@app.post("/api/clear-db")
async def clear_db():
    """Truncate predictions table to clear all historical results."""
    try:
        async with core.db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("TRUNCATE TABLE predictions;")
                await conn.commit()
        return {"success": True, "message": "Database cleared successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Clear database failed: {str(e)}")

# Mount Static frontend assets (dashboard index.html)
public_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
if os.path.exists(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
