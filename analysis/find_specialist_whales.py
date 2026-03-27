#!/usr/bin/env python3
"""
TÌM SPECIALIST WHALES theo tiêu chí:
- avg_size >= $50,000 (trade lớn, có vốn)
- total_trades <= 50 (ít giao dịch - chọn lọc)
- market_diversity <= 3 (chuyên sâu 1-2 category)
- win_rate >= 60% (có edge)
- Kelly >= 0.1 (bankroll management tốt)
- account_age >= 180 days (không phải fresh lucky)
"""
import sqlite3
from collections import defaultdict
from pathlib import Path
from datetime import datetime

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def get_wallet_metrics():
    """Tính toán metrics từ wallet_snapshots + whale_trades"""
    latest_ts = q("SELECT MAX(ts) as ts FROM wallet_snapshots")[0]['ts']

    # Lấy tất cả wallet snapshot mới nhất
    wallets = q("""
        SELECT ws.address, ws.score, ws.win_rate, ws.kelly, ws.total_volume,
               ws.avg_size, ws.trades_per_month, ws.account_age_days,
               ws.total_closed, ws.bot_flag
        FROM wallet_snapshots ws
        WHERE ws.ts = ?
    """, (latest_ts,))

    # Đếm số trades và distinct markets từ whale_trades
    metrics = {}
    for w in wallets:
        addr = w['address']
        trades = q("SELECT * FROM whale_trades WHERE address = ?", (addr,))
        if not trades:
            continue

        # Count distinct markets
        markets = set(t['market_id'] for t in trades if t.get('market_id'))
        market_diversity = len(markets)

        # Total trades
        total_trades = len(trades)

        # Sắp xếp theo avg_size (USDC)
        avg_size = w['avg_size']

        metrics[addr] = {
            **w,
            'total_trades': total_trades,
            'market_diversity': market_diversity,
        }

    return metrics

def find_specialist_whales(metrics, min_avg_size=50000, max_trades=50, max_markets=3, min_wr=60, min_kelly=0.1, min_age=180):
    """Lọc specialist whales"""
    candidates = []
    for addr, m in metrics.items():
        if (m['avg_size'] >= min_avg_size and
            m['total_trades'] <= max_trades and
            m['market_diversity'] <= max_markets and
            m['win_rate'] >= min_wr and
            m['kelly'] >= min_kelly and
            m['account_age_days'] >= min_age and
            not m['bot_flag']):
            candidates.append(m)

    # Sort_by avg_size desc (largest trades first)
    candidates.sort(key=lambda x: x['avg_size'], reverse=True)
    return candidates

def get_top_markets_for_wallet(addr, limit=3):
    """Xem category chính mà wallet này trade"""
    sql = """
    SELECT market_id, COUNT(*) as cnt, AVG(usdc_size) as avg_size
    FROM whale_trades
    WHERE address = ?
    GROUP BY market_id
    ORDER BY cnt DESC, avg_size DESC
    LIMIT ?
    """
    return q(sql, (addr, limit))

def main():
    print("🔍 Loading wallet metrics from DB...")
    metrics = get_wallet_metrics()
    print(f"Total wallets with trades: {len(metrics)}")

    print("\n🎯 SPECIALIST WHALES FILTER")
    print(f"Criteria: avg_size>=$50k, trades<={50}, markets<={3}, WR>={60}%, Kelly>={0.1}, age>={180}d")

    specialists = find_specialist_whales(metrics)
    print(f"\n✅ Found {len(specialists)} specialist whales:\n")

    if not specialists:
        print("No wallets match all criteria. Showing closest candidates:")
        # Show partial matches
        partial = [m for m in metrics.values() if m['avg_size']>=50000 and m['market_diversity']<=3]
        partial.sort(key=lambda x: x['avg_size'], reverse=True)
        for m in partial[:10]:
            print(f"  {m['address'][:12]}... | avg=${m['avg_size']:,.0f} | trades={m['total_trades']} | markets={m['market_diversity']} | wr={m['win_rate']:.1f}% | kelly={m['kelly']:.3f}")
        return

    # Hiển thị chi tiết specialists
    for i, w in enumerate(specialists, 1):
        addr = w['address']
        top_markets = get_top_markets_for_wallet(addr, 3)
        print(f"{i}. {addr}")
        print(f"   Score: {w['score']:.2f} | WR: {w['win_rate']:.1f}% | Kelly: {w['kelly']:.3f}")
        print(f"   Avg trade: ${w['avg_size']:,.0f} | Total trades: {w['total_trades']} | Markets: {w['market_diversity']}")
        print(f"   Total volume: ${w['total_volume']:,.0f} | Age: {w['account_age_days']}d")
        print(f"   Top markets:")
        for m in top_markets:
            print(f"     • {m['market_id'][:40]}... | count={m['cnt']} | avg=${m['avg_size']:,.0f}")
        print()

    # Summary by market_diversity
    print("\n📊 Specialist whales by market focus:")
    groups = defaultdict(list)
    for w in specialists:
        groups[w['market_diversity']].append(w)
    for div in sorted(groups.keys()):
        print(f"  {div} market(s): {len(groups[div])} wallets")

    print("\n💡 INSIGHTS:")
    print("  • These wallets trade infrequently but with large sizes → likely insider/edge")
    print("  • Low market diversity suggests deep expertise in specific domains")
    print("  • High Kelly (0.1+) indicates prudent position sizing relative to win rate")
    print("  • Recommend: prioritize these for copy-trading with position scaling")

    print("\n📁 Saving specialist list to /tmp/specialist_whales.json ...")
    import json
    with open('/tmp/specialist_whales.json', 'w') as f:
        json.dump(specialists, f, indent=2)
    print("✅ Done.")

if __name__ == "__main__":
    main()
