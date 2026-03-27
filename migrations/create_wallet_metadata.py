#!/usr/bin/env python3
"""Create wallet_metadata table for incremental refresh tracking."""
import sqlite3

DB_PATH = '/root/polymarket/shared/db/polybot.db'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Check if table exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wallet_metadata'")
if cur.fetchone():
    print("✅ wallet_metadata table already exists")
else:
    cur.execute("""
        CREATE TABLE wallet_metadata (
            address TEXT PRIMARY KEY,
            last_full_fetch_ts INTEGER DEFAULT 0,
            trade_count INTEGER DEFAULT 0,
            needs_refresh INTEGER DEFAULT 1,
            last_updated INTEGER DEFAULT 0
        )
    """)
    db.commit()
    print("✅ Created wallet_metadata table")

# Add index for faster queries
cur.execute("CREATE INDEX IF NOT EXISTS idx_wallet_metadata_address ON wallet_metadata(address)")
db.commit()

db.close()
print("✅ Migration complete")
