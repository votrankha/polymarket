#!/usr/bin/env python3
"""Update specialist whales with primary_category từ enriched data"""
import sqlite3
import json
from pathlib import Path

DB = Path("/root/polymarket/shared/db/polybot.db")
ENRICHED = Path("/tmp/specialist_whales_ENRICHED.json")

def main():
    with open(ENRICHED) as f:
        specialists = json.load(f)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Lấy MAX(ts) để update đúng batch snapshot
    cur.execute("SELECT MAX(ts) FROM wallet_snapshots")
    max_ts = cur.fetchone()[0]

    for s in specialists:
        addr = s['address']
        cat = s['primary_category']
        # Update row với address và ts gần nhất
        cur.execute('''
            UPDATE wallet_snapshots
            SET primary_category = ?
            WHERE address = ? AND ts = ?
        ''', (cat, addr, max_ts))
        if cur.rowcount > 0:
            print(f"✅ {addr[:12]}... -> {cat}")
        else:
            # Nếu không tìm thấy ở ts mới nhất, tìm ở bất kỳ ts nào
            cur.execute('''
                UPDATE wallet_snapshots
                SET primary_category = ?
                WHERE address = ? AND ts = (SELECT MAX(ts) FROM wallet_snapshots WHERE address = ?)
            ''', (cat, addr, addr))
            print(f"⚠️  {addr[:12]}... (fallback update) -> {cat}")

    conn.commit()
    conn.close()
    print("\n📊 Verifying...")
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT primary_category, COUNT(*) FROM wallet_snapshots WHERE specialist=1 GROUP BY primary_category")
    rows = cur.fetchall()
    for cat, cnt in rows:
        print(f"  {cat}: {cnt}")
    conn.close()
    print("✅ Done.")

if __name__ == "__main__":
    main()
