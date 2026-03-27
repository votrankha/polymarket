#!/usr/bin/env python3
"""
RECALCULATE WALLET METRICS AFTER DATA FIX
-----------------------------------------
Sau khi sửa closed_positions, cần recalc:
- win_rate
- kelly_fraction
- total_pnl
- avg_win, avg_loss
- trades_per_month
- market_count
- total_volume (from whale_trades)

Ứng với tất cả wallets đã theo dõi (tracked_wallets.json).
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

DB = Path("/root/polymarket/shared/db/polybot.db")
WALLET_FILE = Path("/root/polymarket/shared/db/tracked_wallets.json")

def get_wallet_stats(address):
    """Calculate current stats from closed_positions"""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Tổng quát closed positions
    cur.execute("""
        SELECT 
            COUNT(*) as total_closed,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
            SUM(realized_pnl) as total_pnl,
            SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END) as total_win,
            SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END) as total_loss,
            AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_win,
            AVG(CASE WHEN realized_pnl < 0 THEN realized_pnl END) as avg_loss,
            COUNT(DISTINCT market_id) as market_count
        FROM closed_positions
        WHERE address = ?
    """, (address,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        conn.close()
        return None

    total_closed, wins, losses, total_pnl, total_win, total_loss, avg_win, avg_loss, market_count = row

    # Tính win rate
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

    # Lấy avg_size, total_volume từ whale_trades
    cur.execute("""
        SELECT AVG(usdc_size) as avg_size, SUM(usdc_size) as total_volume, COUNT(*) as total_trades
        FROM whale_trades
        WHERE address = ?
    """, (address,))
    row2 = cur.fetchone()
    if row2 and row2[0]:
        avg_size = row2[0] or 0
        total_volume = row2[1] or 0
        total_trades = row2[2] or 0
    else:
        avg_size = 0
        total_volume = 0
        total_trades = 0

    # Tính trades_per_month (từ whale_trades và thời gian)
    cur.execute("SELECT MIN(ts), MAX(ts) FROM whale_trades WHERE address = ?", (address,))
    row3 = cur.fetchone()
    if row3 and row3[0] and row3[1]:
        months_span = (row3[1] - row3[0]) / (30 * 86400)
        trades_per_month = total_trades / months_span if months_span > 0 else 0
    else:
        trades_per_month = 0

    # Tính Kelly fraction
    # Kelly = (win_rate * avg_win) / abs(avg_loss) - (loss_rate / avg_win) hoặc công thức đơn giản
    # Dùng công thức: f* = (p * b - q) / b, với p=win_rate, q=loss_rate, b=avg_win/abs(avg_loss)
    if avg_win and avg_loss and avg_loss < 0:
        p = wins / total_closed if total_closed else 0
        q = losses / total_closed if total_closed else 0
        b = avg_win / abs(avg_loss)
        if b > 0:
            kelly = p - (q / b)
        else:
            kelly = 0.0
    else:
        kelly = 0.0

    # Net PnL (từ closed_positions)
    net_pnl = total_pnl

    # account_age_days từ whale_trades
    cur.execute("SELECT MIN(ts), MAX(ts) FROM whale_trades WHERE address = ?", (address,))
    row4 = cur.fetchone()
    if row4 and row4[0]:
        first_ts = row4[0]
        account_age_days = (int(datetime.now().timestamp()) - first_ts) / 86400
    else:
        account_age_days = 0

    conn.close()

    return {
        'address': address,
        'win_rate': round(win_rate, 2),
        'kelly': round(max(kelly, 0), 4),
        'net_pnl': round(net_pnl, 2),
        'avg_size': round(avg_size, 2),
        'total_volume': round(total_volume, 2),
        'total_closed': total_closed,
        'market_count': market_count,
        'trades_per_month': round(trades_per_month, 2),
        'account_age_days': round(account_age_days, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_win': round(avg_win, 2) if avg_win else 0,
        'avg_loss': round(avg_loss, 2) if avg_loss else 0,
        'total_trades': total_trades
    }

def recalc_all_tracked():
    # Load tracked wallets
    with open(WALLET_FILE, 'r') as f:
        tracked = json.load(f)

    print(f"Recalculating stats for {len(tracked)} tracked wallets...")
    updates = []

    for addr in tracked:
        stats = get_wallet_stats(addr)
        if stats:
            # Update tracked entry
            old = tracked[addr]
            old.update({
                'win_rate': stats['win_rate'],
                'kelly': stats['kelly'],
                'net_pnl': stats['net_pnl'],
                'avg_size': stats['avg_size'],
                'total_volume': stats['total_volume'],
                'total_closed': stats['total_closed'],
                'market_count': stats['market_count'],
                'trades_per_month': stats['trades_per_month'],
                'account_age_days': stats['account_age_days'],
                'avg_win': stats['avg_win'],
                'avg_loss': stats['avg_loss']
            })
            updates.append(addr)

    # Save back
    with open(WALLET_FILE, 'w') as f:
        json.dump(tracked, f, indent=2)

    print(f"✅ Updated tracked_wallets.json: {len(updates)} wallets")
    return len(updates)

def main():
    print("🔧 RECALCULATING WALLET METRICS FROM FIXED DATA")
    print("=" * 60)
    count = recalc_all_tracked()
    print("=" * 60)
    print(f"Done: {count} wallets updated.")

if __name__ == "__main__":
    main()
