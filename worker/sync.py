import asyncio
import datetime
import httpx
from core.db import pool
from core.oracle import Oracle

# Global in-memory state for tracking predictions and period transitions
state = {
    "last_id": None,
    "last_pred": None, # { 'n': int, 'sz': str, 'col': str, 'method': str, 'confidence': int, 'target_id': str }
}

def get_now_ist():
    """Get current IST date and time components."""
    # IST is UTC + 5:30
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    return {
        "date": ist_now.strftime("%Y-%m-%d"),
        "time": ist_now.strftime("%H:%M:%S"),
        "hour": ist_now.hour
    }

async def fetch_history() -> list:
    """Fetch recent history list from the original game API."""
    url = f"https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?ts={int(datetime.datetime.now().timestamp() * 1000)}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "referer": "https://draw.ar-lottery01.com/"
    }
    async with httpx.AsyncClient(timeout=8.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            return data.get("data", {}).get("list", []) or data.get("recent", []) or []
    return []

async def sync_round() -> bool:
    """Core synchronization loop. Returns True if a new round was successfully processed."""
    global state
    try:
        recent_list = await fetch_history()
        if not recent_list:
            print("[SYNC] No history data received from game API.")
            return False

        # Extract latest completed round
        latest_period = str(recent_list[0]["issueNumber"])
        latest_num = int(recent_list[0]["number"])
        latest_size = "BIG" if latest_num >= 5 else "SMALL"
        latest_color = Oracle.get_color(latest_num)

        # 1. Automatically backfill the recent 15 rounds to Neon using DO NOTHING on conflict
        ist = get_now_ist()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                for r in reversed(recent_list):
                    r_id = str(r["issueNumber"])
                    r_num = int(r["number"])
                    r_size = "BIG" if r_num >= 5 else "SMALL"
                    r_color = Oracle.get_color(r_num)
                    
                    await cur.execute(
                        """
                        INSERT INTO predictions (game_type, date_ist, time_ist, hour_ist, period_id, actual_num, actual_size, actual_color, pred_num, pred_size, pred_color, pattern_used, num_win, size_win, color_win, confidence, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (game_type, period_id) DO NOTHING
                        """,
                        ["1M", ist["date"], ist["time"], ist["hour"], r_id, r_num, r_size, r_color, 5, "BIG", "GREEN_VIOLET", "API_FALLBACK", "LOSS", "LOSS", "LOSS", 10, "PYTHON_ENGINE"]
                    )
                await conn.commit()

        print(f"[SYNC] Latest completed Period ID from API: {latest_period}")

        # Check if period is already processed
        if state["last_id"] == latest_period:
            print(f"[SYNC] Period {latest_period} already processed. Skipping.")
            return False
        state["last_id"] = latest_period

        # 2. Process active previous prediction, calculating win outcomes and updating the row in Neon
        if state["last_pred"] and state["last_pred"]["target_id"] == latest_period:
            pred = state["last_pred"]
            num_win = "WIN" if latest_num == pred["n"] else "LOSS"
            size_win = "WIN" if latest_size == pred["sz"] else "LOSS"
            color_win = "WIN" if (latest_color in pred["col"] or pred["col"] in latest_color) else "LOSS"

            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO predictions (game_type, date_ist, time_ist, hour_ist, period_id, actual_num, actual_size, actual_color, pred_num, pred_size, pred_color, pattern_used, num_win, size_win, color_win, confidence, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (game_type, period_id) DO UPDATE SET
                            pred_num = EXCLUDED.pred_num, pred_size = EXCLUDED.pred_size, pred_color = EXCLUDED.pred_color,
                            pattern_used = EXCLUDED.pattern_used, num_win = EXCLUDED.num_win, size_win = EXCLUDED.size_win,
                            color_win = EXCLUDED.color_win, confidence = EXCLUDED.confidence
                        """,
                        ["1M", ist["date"], ist["time"], ist["hour"], latest_period, latest_num, latest_size, latest_color, pred["n"], pred["sz"], pred["col"], pred["method"], num_win, size_win, color_win, pred["confidence"], "PYTHON_ENGINE"]
                    )
                await conn.commit()
            print(f"[SYNC] {latest_period} | Size Outcome: {size_win} | Color Outcome: {color_win} | Strategy: {pred['method']}")

        # 3. Predict the next round instantly in < 1ms using the updated database history
        next_period = str(int(latest_period) + 1)
        print(f"[SYNC] Preparing prediction for next Period: {next_period}")

        # Format historical list for the oracle engine
        formatted_history = [{"num": int(r["number"])} for r in recent_list[:10]]
        signal = Oracle.get_signal(formatted_history)

        state["last_pred"] = {
            "n": signal["number"],
            "sz": signal["size"],
            "col": signal["color"],
            "method": signal["method"],
            "confidence": signal["confidence"],
            "target_id": next_period
        }
        print(f"[SYNC] Active prediction updated: Period {next_period} | Predicted: {signal['number']} ({signal['size']}) | Strategy: {signal['method']}")
        return True

    except Exception as e:
        print(f"[SYNC ERROR] Failed in synchronization loop: {str(e)}")
        return False

async def worker_loop():
    """Clock-synchronized async polling loop."""
    print("[WORKER] Background clock-synchronized worker started.")
    
    # Run initial sync immediately to backfill and set initial state
    await sync_round()
    
    while True:
        try:
            now = datetime.datetime.now()
            seconds = now.second
            
            # Target the exact 03-second mark of the next minute (creating a 3-second buffer for the game result publication)
            delay = 60 - seconds + 3
            if seconds < 3:
                delay = 3 - seconds
                
            await asyncio.sleep(delay)
            
            success = await sync_round()
            if not success:
                # Upgraded 4-second retry cooldown if the API was delayed
                print(f"[WORKER] Cooldown active. Retrying in 4 seconds...")
                await asyncio.sleep(4)
                await sync_round()
                
        except asyncio.CancelledError:
            print("[WORKER] Polling task cancelled.")
            break
        except Exception as e:
            print(f"[WORKER ERROR] Unexpected failure in background loop: {str(e)}")
            await asyncio.sleep(5)
