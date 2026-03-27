#!/usr/bin/env python3
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import json

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "shared" / "db" / "polybot.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Lấy tất cả addresses
cur.execute("SELECT DISTINCT address FROM whale_trades")
addresses = [row['address'] for row in cur.fetchall()]
print(f"Wallets with trades: {len(addresses)}")

stats_list = []
for addr in addresses[:200]:  # sample 200
    cur.execute("SELECT COUNT(*) as cnt, MIN(ts) as min_ts, MAX(ts) as max_ts FROM whale_trades WHERE address=?", (addr,))
    row = cur.fetchone()
    n_trades = row['cnt']
    min_ts = row['min_ts']
    max_ts = row['max_ts']
    now = int(datetime.now(timezone.utc).timestamp())
    if min_ts and min_ts > 0:
        age_days = max(1, (now - min_ts) // 86400)
    else:
        age_days = 1

    cur.execute("SELECT COUNT(*) as cnt FROM closed_positions WHERE address=?", (addr,))
    n_closed = cur.fetchone()['cnt']

    cur.execute("SELECT SUM(usdc_size) as vol FROM whale_trades WHERE address=?", (addr,))
    vol = cur.fetchone()['vol'] or 0

    # market count
    cur.execute("SELECT COUNT(DISTINCT market_id) as mcnt FROM whale_trades WHERE address=?", (addr,))
    mkt_cnt = cur.fetchone()['mcnt']

    stats_list.append({
        'address': addr,
        'n_trades': n_trades,
        'age_days': age_days,
        'n_closed': n_closed,
        'volume': vol,
        'mkt_cnt': mkt_cnt,
        'trades_per_month': n_trades / max(1, age_days/30)
    })

conn.close()

# Phân tích phân phối
print("\n--- Statistics (sample 200) ---")
def print_dist(key, bins):
    vals = [s[key] for s in stats_list]
    print(f"\n{key}: min={min(vals):.1f}, max={max(vals):.1f}")
    for b in bins:
        cnt = sum(1 for v in vals if v >= b[0] and v < b[1])
        print(f"  [{b[0]}, {b[1]}) : {cnt}")

print_dist('age_days', [(0,1),(1,7),(7,30),(30,90),(90,365),(365,1e9)])
print_dist('n_closed', [(0,1),(1,3),(3,5),(5,10),(10,50),(50,1e9)])
print_dist('trades_per_month', [(0,5),(5,10),(10,50),(50,150),(150,300),(300,1e9)])
print_dist('mkt_cnt', [(0,1),(1,3),(3,5),(5,10),(10,1e9)])

# Lưu sample để inspect
with open('/root/polymarket/scripts/stats_sample.json', 'w') as f:
    json.dump(stats_list, f, indent=2)
print("\nSample saved to scripts/stats_sample.json")
