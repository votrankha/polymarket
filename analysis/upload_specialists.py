#!/usr/bin/env python3
"""
MANUAL UPLOAD: Nhúng specialist whales vào wallet_snapshots DB
Dùng khi bootstrap không phát hiện do họ không trong leaderboard.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB = Path("/root/polymarket/shared/db/polybot.db")

SPECIALISTS_JSON = Path('/tmp/specialist_whales_ENRICHED.json')

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return [dict(r) for r in conn.execute(sql, params)]

def upsert_specialist(wallet: dict):
    """
    Insert/update wallet_snapshots với specialist=1.
    """
    addr = wallet['address'].lower()
    now = int(datetime.now().timestamp())

    # Lấy thêm metrics từ DB nếu có
    # total_closed từ closed_positions
    closed = q("SELECT realized_pnl FROM closed_positions WHERE address = ?", (addr,))
    total_closed = len(closed)
    wins = sum(1 for p in closed if float(p['realized_pnl'] or 0) > 0)
    wr = (wins / total_closed * 100) if total_closed > 0 else 0.0
    # Kelly
    win_pnls = [float(p['realized_pnl']) for p in closed if float(p['realized_pnl']) > 0]
    loss_pnls = [abs(float(p['realized_pnl'])) for p in closed if float(p['realized_pnl']) < 0]
    avg_win = sum(win_pnls)/len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls)/len(loss_pnls) if loss_pnls else 1
    b = avg_win/avg_loss if avg_loss>0 else 0
    p = len(win_pnls)/total_closed if total_closed>0 else 0
    kelly = max(0.0, (p*b - (1-p))/b) if b>0 else 0.0

    # trades count và ts span từ large trades (>=10k)
    trades = q("""
        SELECT COUNT(*) as cnt, MIN(ts) as min_ts, MAX(ts) as max_ts
        FROM whale_trades
        WHERE address = ? AND usdc_size >= 10000
    """, (addr,))
    if trades:
        t = trades[0]
        total_trades = t['cnt'] or 0
        if t['min_ts'] and t['max_ts']:
            days_span = max(1, (t['max_ts'] - t['min_ts']) / 86400)
            trades_per_month = total_trades / (days_span / 30)
        else:
            trades_per_month = 0
    else:
        total_trades = 0
        trades_per_month = 0

    # avg_size, total_volume chỉ từ LARGE trades (>=10k) để đúng với specialist criteria
    agg = q("""
        SELECT AVG(usdc_size) as avg_size, SUM(usdc_size) as total_volume
        FROM whale_trades
        WHERE address = ? AND usdc_size >= 10000
    """, (addr,))
    avg_size = agg[0]['avg_size'] or 0 if agg else 0
    total_volume = agg[0]['total_volume'] or 0 if agg else 0

    # account_age_days: từ whale_trades min_ts
    if trades and t['min_ts']:
        account_age_days = int((now - t['min_ts']) / 86400)
    else:
        account_age_days = 0

    # bot_flag: kiểm tra từ wallet_snapshots cũ nếu có, hoặc false
    bot_flag = 0

    # Score: có thể lấy từ wallet cũ nếu có, hoặc tính tạm
    # Từ enriched, có score sẵn
    score = wallet.get('score', 0.5)

    # Insert/Update
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # Check if exists at latest ts batch
    cur.execute("SELECT MAX(ts) FROM wallet_snapshots")
    max_ts_row = cur.fetchone()
    max_ts = max_ts_row[0] if max_ts_row and max_ts_row[0] else 0
    cur.execute("SELECT 1 FROM wallet_snapshots WHERE address = ? AND ts = ?", (addr, max_ts))
    existing = cur.fetchone()

    if existing:
        # Update
        cur.execute('''
            UPDATE wallet_snapshots
            SET score = ?, win_rate = ?, kelly = ?, net_pnl = ?,
                avg_size = ?, total_closed = ?, trades_per_month = ?,
                account_age_days = ?, total_volume = ?, bot_flag = ?,
                specialist = ?
            WHERE address = ? AND ts = ?
        ''', (
            score, wr, kelly, 0.0,
            avg_size, total_closed, trades_per_month,
            account_age_days, total_volume, bot_flag,
            1,  # specialist
            addr, max_ts
        ))
    else:
        # Insert new snapshot with current ts
        cur.execute('''
            INSERT INTO wallet_snapshots
            (address, ts, score, win_rate, kelly, net_pnl, avg_size, total_closed,
             trades_per_month, account_age_days, total_volume, bot_flag, specialist, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            addr, now, score, wr, kelly, 0.0, avg_size, total_closed,
            trades_per_month, account_age_days, total_volume, bot_flag,
            1, 'manual_upload'
        ))
    conn.commit()
    conn.close()
    print(f"✅ Upserted {addr} →WR={wr:.1f}% kelly={kelly:.4f} avg=${avg_size:,.0f} specialist=1")

def main():
    print("🔧 Manually uploading specialist whales to wallet_snapshots...\n")
    with open(SPECIALISTS_JSON) as f:
        specialists = json.load(f)

    print(f"Loaded {len(specialists)} specialists\n")

    for w in specialists:
        try:
            upsert_specialist(w)
        except Exception as e:
            print(f"❌ Error for {w['address']}: {e}")

    print("\n📊 Verifying...")
    count = q("SELECT COUNT(*) as cnt FROM wallet_snapshots WHERE specialist = 1")[0]['cnt']
    print(f"Total specialist wallets in DB: {count}")
    print("✅ Done.")

if __name__ == "__main__":
    main()
