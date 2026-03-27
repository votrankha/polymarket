#!/usr/bin/env python3
"""
FIND SPECIALIST WHALES across ALL wallets in whale_trades
Criteria:
  avg_size >= $50,000  (large bets)
  total_trades <= 50   (infrequent, selective)
  market_diversity <= 3 (specialized)
"""
import sqlite3
from pathlib import Path
from collections import Counter

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def main():
    print("🔍 Querying whale_trades for specialist pattern...")

    # Group by address
    sql = """
    SELECT address,
           COUNT(*) as total_trades,
           AVG(usdc_size) as avg_size,
           COUNT(DISTINCT market_id) as market_diversity,
           SUM(usdc_size) as total_volume,
           MIN(ts) as first_ts,
           MAX(ts) as last_ts
    FROM whale_trades
    WHERE usdc_size >= 10000  -- only large trades
    GROUP BY address
    HAVING COUNT(*) >= 5  -- at least 5 trades to consider
    ORDER BY avg_size DESC
    """
    rows = q(sql)
    print(f"Wallets with large trades ($10k+): {len(rows)}")

    # Filter specialist: large avg, few trades, few markets
    specialists = []
    for r in rows:
        if r['avg_size'] >= 50000 and r['total_trades'] <= 50 and r['market_diversity'] <= 3:
            specialists.append(dict(r))

    print(f"Specialist candidates (avg>=$50k, trades<=50, markets<=3): {len(specialists)}\n")

    if not specialists:
        print("No specialist whales found. Relaxing criteria...")
        # Show closest
        partial = [r for r in rows if r['avg_size'] >= 50000 and r['market_diversity'] <= 3]
        partial.sort(key=lambda x: x['avg_size'], reverse=True)
        print("\nTop 10 wallets with avg>=$50k and markets<=3 (any trade count):")
        for i, r in enumerate(partial[:10], 1):
            print(f"  {i}. {r['address'][:12]}... avg=${r['avg_size']:,.0f} trades={r['total_trades']} markets={r['market_diversity']}")
        return

    # For each specialist, get top markets
    for i, s in enumerate(specialists, 1):
        addr = s['address']
        print(f"{i}. {addr}")
        print(f"   Avg trade: ${s['avg_size']:,.0f} | Total trades: {s['total_trades']} | Markets: {s['market_diversity']}")
        print(f"   Total volume: ${s['total_volume']:,.0f}")
        # Get top 3 markets
        top_markets = q("""
            SELECT market_id, COUNT(*) as cnt, AVG(usdc_size) as avg
            FROM whale_trades
            WHERE address = ?
            GROUP BY market_id
            ORDER BY cnt DESC, avg DESC
            LIMIT 3
        """, (addr,))
        print(f"   Top markets:")
        for m in top_markets:
            print(f"     • {m['market_id'][:50]}... | {m['cnt']} trades, avg=${m['avg']:,.0f}")
        print()

    print("\n📊 Summary:")
    print(f"  Total specialist whales found: {len(specialists)}")
    if specialists:
        avg_sizes = [s['avg_size'] for s in specialists]
        print(f"  Avg trade size range: ${min(avg_sizes):,.0f} - ${max(avg_sizes):,.0f}")

    print("\n💡 INSIGHTS:")
    print("  • These wallets bet big on few markets → likely have strong conviction/edge")
    print("  • They are the BEST candidates for copy-trading:")
    print("    - High conviction (large bet size)")
    print("    - Focused expertise (specialized)")
    print("    - Not bots (few trades)")
    print("  • Action: Add to wallet.md as priority copy targets immediately")
    print("\n📁 Saving specialist list to /tmp/specialist_whales_ALL.json ...")
    import json, datetime
    # Convert to JSON-serializable
    out = []
    for s in specialists:
        out.append({
            'address': s['address'],
            'avg_size_usd': round(s['avg_size'], 2),
            'total_trades': int(s['total_trades']),
            'market_diversity': int(s['market_diversity']),
            'total_volume_usd': round(s['total_volume'], 2),
            'activity_span_days': round((s['last_ts'] - s['first_ts']) / 86400, 1) if s['last_ts'] > s['first_ts'] else 0,
        })
    with open('/tmp/specialist_whales_ALL.json', 'w') as f:
        json.dump(out, f, indent=2)
    print("✅ Done.")

if __name__ == "__main__":
    main()
