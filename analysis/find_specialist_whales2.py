#!/usr/bin/env python3
"""
Find specialist whales with LARGE position sizes but FEW trades and SPECIALIZED markets.
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def get_snapshot_metrics():
    """Lấy win_rate, kelly, age từ wallet_snapshots latest"""
    latest_ts = q("SELECT MAX(ts) as ts FROM wallet_snapshots")[0]['ts']
    rows = q("""
        SELECT address, win_rate, kelly, account_age_days, bot_flag, total_closed
        FROM wallet_snapshots
        WHERE ts = ?
    """, (latest_ts,))
    return {r['address']: dict(r) for r in rows}

def get_trade_metrics():
    """Tính avg_size, total_trades, market diversity từ whale_trades"""
    sql = """
    SELECT address,
           COUNT(*) as total_trades,
           AVG(usdc_size) as avg_size,
           COUNT(DISTINCT market_id) as market_diversity,
           SUM(usdc_size) as total_volume
    FROM whale_trades
    GROUP BY address
    HAVING COUNT(*) >= 5  -- at least 5 trades to be meaningful
    """
    rows = q(sql)
    return {r['address']: dict(r) for r in rows}

def main():
    print("🔍 Loading data from DB...")
    snap = get_snapshot_metrics()
    trades = get_trade_metrics()

    # Merge
    all_addresses = set(snap.keys()) & set(trades.keys())
    print(f"Wallets with snapshot: {len(snap)}")
    print(f"Wallets with trades: {len(trades)}")
    print(f"Wallets with both: {len(all_addresses)}")

    # Specialist criteria:
    # avg_size >= $50,000
    # total_trades <= 50
    # market_diversity <= 3
    # win_rate >= 60
    # kelly >= 0.1
    # account_age_days >= 180
    # not bot_flag

    candidates = []
    for addr in all_addresses:
        s = snap[addr]
        t = trades[addr]

        if s.get('bot_flag'):
            continue
        if s.get('account_age_days', 0) < 180:
            continue
        if s.get('win_rate', 0) < 60:
            continue
        if s.get('kelly', 0) < 0.1:
            continue
        if t['avg_size'] < 50000:
            continue
        if t['total_trades'] > 50:
            continue
        if t['market_diversity'] > 3:
            continue

        candidates.append({
            'address': addr,
            'avg_size': round(t['avg_size'], 2),
            'total_trades': t['total_trades'],
            'market_diversity': t['market_diversity'],
            'total_volume': round(t['total_volume'], 2),
            'win_rate': s['win_rate'],
            'kelly': s['kelly'],
            'account_age_days': s['account_age_days'],
        })

    # Sort by avg_size desc (largest bets)
    candidates.sort(key=lambda x: x['avg_size'], reverse=True)

    print(f"\n🎯 SPECIALIST WHALES (large bets, few trades, specialized):")
    print(f"Criteria: avg_size>=$50k, trades<=50, markets<=3, WR>=60%, Kelly>=0.1, age>=180d, no bot")
    print(f"\nFound {len(candidates)} specialist whales:\n")

    if not candidates:
        print("None found. Consider relaxing criteria:")
        # Show partial matches
        print("\n  Wallets with avg_size>=$50k and markets<=3 (any trades count):")
        partial = []
        for addr in all_addresses:
            t = trades[addr]
            s = snap[addr]
            if t['avg_size'] >= 50000 and t['market_diversity'] <= 3 and not s.get('bot_flag'):
                partial.append({
                    'address': addr,
                    'avg_size': round(t['avg_size'], 2),
                    'total_trades': t['total_trades'],
                    'market_diversity': t['market_diversity'],
                    'win_rate': s['win_rate'],
                    'kelly': s['kelly'],
                })
        partial.sort(key=lambda x: x['avg_size'], reverse=True)
        for p in partial[:10]:
            print(f"    {p['address'][:12]}... avg=${p['avg_size']:,.0f} trades={p['total_trades']} markets={p['market_diversity']} wr={p['win_rate']:.1f}% kelly={p['kelly']:.3f}")
        return

    for i, w in enumerate(candidates, 1):
        print(f"{i}. {w['address']}")
        print(f"   Avg trade: ${w['avg_size']:,.0f} | Total trades: {w['total_trades']} | Markets: {w['market_diversity']}")
        print(f"   Total volume: ${w['total_volume']:,.0f} | WR: {w['win_rate']:.1f}% | Kelly: {w['kelly']:.3f} | Age: {w['account_age_days']}d")
        print()

    # Summary
    print("\n📊 By market focus:")
    by_markets = defaultdict(list)
    for w in candidates:
        by_markets[w['market_diversity']].append(w)
    for div in sorted(by_markets.keys()):
        print(f"  {div} market(s): {len(by_markets[div])} wallets")

    if candidates:
        print("\n💎 Top 3 specialists (by avg_size):")
        for w in candidates[:3]:
            print(f"  • {w['address']} - ${w['avg_size']:,.0f}/trade, {w['market_diversity']} markets, WR={w['win_rate']:.1f}%")

    print("\n📁 Saving to /tmp/specialist_whales.json ...")
    import json
    with open('/tmp/specialist_whales.json', 'w') as f:
        json.dump(candidates, f, indent=2)
    print("✅ Done.")

if __name__ == "__main__":
    main()
