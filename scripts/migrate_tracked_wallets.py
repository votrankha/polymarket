#!/usr/bin/env python3
"""
Migration script: Move tracked_wallets.json into polybot.db wallet_snapshots table
"""

import json
import sqlite3
import os
import sys
import time
from pathlib import Path

def main():
    print("🔄 Starting migration of tracked wallets...")
    
    # Paths
    json_path = Path("/root/.openclaw/workspace-bob/shared/db/tracked_wallets.json")
    backup_path = Path("/root/.openclaw/workspace-bob/shared/db/tracked_wallets.json.backup")
    db_path = Path("/root/.openclaw/workspace-bob/shared/db/polybot.db")
    
    # Step 1: Use existing backup
    if backup_path.exists():
        print(f"✅ Using existing backup: {backup_path}")
    else:
        print(f"⚠️  {backup_path} not found, nothing to migrate")
        return
    
    # Step 2: Read JSON data
    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            wallets = json.load(f)
        print(f"✅ Read {len(wallets)} wallets from JSON")
    except Exception as e:
        print(f"❌ Failed to read JSON: {e}")
        return
    
    # Step 3: Connect to SQLite and migrate
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create wallet_snapshots table if it doesn't exist (should exist already)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_snapshots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                address          TEXT NOT NULL,
                ts               INTEGER NOT NULL,
                score            REAL,
                win_rate         REAL,
                kelly            REAL,
                net_pnl          REAL,
                avg_size         REAL,
                total_closed     INTEGER,
                trades_per_month REAL,
                account_age_days INTEGER,
                total_volume     REAL,
                bot_flag         INTEGER DEFAULT 0,
                source           TEXT DEFAULT 'scan'
            )
        ''')
        
        # Insert wallets with current timestamp
        current_ts = int(time.time())
        inserted = 0
        for addr, data in wallets.items():
            cursor.execute('''
                INSERT OR REPLACE INTO wallet_snapshots 
                (address, ts, score, win_rate, kelly, net_pnl, avg_size, total_closed,
                 trades_per_month, account_age_days, total_volume, bot_flag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['address'],
                current_ts,
                data.get('score'),
                data.get('win_rate'),
                data.get('kelly'),
                data.get('net_pnl'),
                data.get('avg_size'),
                data.get('total_closed'),
                data.get('trades_per_month'),
                data.get('account_age_days'),
                data.get('total_volume'),
                1 if data.get('bot_flag') else 0
            ))
            inserted += 1
        
        conn.commit()
        print(f"✅ Inserted {inserted} wallets into wallet_snapshots")
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ws_address ON wallet_snapshots(address)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ws_ts ON wallet_snapshots(ts)')
        
        # Verify migration
        cursor.execute('SELECT COUNT(*) FROM wallet_snapshots WHERE ts = ?', (current_ts,))
        count = cursor.fetchone()[0]
        print(f"✅ Verification: {count} wallets have current timestamp")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return
    finally:
        if 'conn' in locals():
            conn.close()
    
    print("✅ Migration completed successfully!")
    print("📋 Next steps:")
    print("   1. Modify agent1_whale_hunter.py to use SQLite instead of JSON")
    print("   2. Test the modified agent")
    print("   3. Delete tracked_wallets.json after 1 hour of stable operation")

if __name__ == '__main__':
    main()