import os
import asyncio
from psycopg_pool import AsyncConnectionPool

# Read connection string, strictly defaulting to a safe placeholder to prevent GitHub security suspensions.
# Your live database URL should be set securely via the "DATABASE_URL" environment variable on Render.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:YOUR_SECRET_PASSWORD@ep-YOUR-POOLER-POOL.aws.neon.tech/neondb?sslmode=require"
)

# Initialize global async connection pool
pool = None

async def init_db():
    global pool
    print("[DB] Initializing Neon Async Connection Pool...")
    pool = AsyncConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, open=False)
    await pool.open()
    
    # Run automatic database migrations to ensure table schema is ready
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id SERIAL PRIMARY KEY,
                    game_type VARCHAR(10) NOT NULL,
                    date_ist VARCHAR(20) NOT NULL,
                    time_ist VARCHAR(20) NOT NULL,
                    hour_ist INTEGER NOT NULL,
                    period_id VARCHAR(50) NOT NULL,
                    actual_num INTEGER NOT NULL,
                    actual_size VARCHAR(10) NOT NULL,
                    actual_color VARCHAR(20) NOT NULL,
                    pred_num INTEGER,
                    pred_size VARCHAR(10),
                    pred_color VARCHAR(20),
                    pattern_used VARCHAR(50),
                    num_win VARCHAR(10),
                    size_win VARCHAR(10),
                    color_win VARCHAR(10),
                    confidence INTEGER,
                    source VARCHAR(20) DEFAULT 'PYTHON_ENGINE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_game_period UNIQUE (game_type, period_id)
                );
            """)
            await conn.commit()
            print("[DB] Neon Table 'predictions' Checked and Ready ✅")

async def close_db():
    global pool
    if pool:
        print("[DB] Closing Async Connection Pool...")
        await pool.close()
