#!/usr/bin/env python3
"""
ENRICH SPECIALIST WHALES with:
- Market categories (from markets table)
- Performance metrics (win_rate, kelly from closed_positions)
- Are they already promoted? (check wallet_snapshots)
"""
import sqlite3
import json
from collections import Counter
from pathlib import Path
from datetime import datetime

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def get_market_category(condition_id: str) -> str:
    """Lấy category từ markets table"""
    r = q("SELECT category, question FROM markets WHERE condition_id = ?", (condition_id,))
    if r:
        cat = r[0]['category'] or 'Uncategorized'
        ques = r[0]['question'] or ''
        return cat, ques[:80]
    return 'Unknown', ''

def compute_performance_from_closed(address: str) -> dict:
    """Tính WR, Kelly, avg_win, avg_loss từ closed_positions"""
    pos = q("SELECT realized_pnl FROM closed_positions WHERE address = ?", (address,))
    if not pos:
        return {'wr': 0, 'kelly': 0, 'total': 0, 'wins': 0, 'losses': 0, 'avg_win': 0, 'avg_loss': 0}

    wins = []
    losses = []
    for p in pos:
        pnl = float(p['realized_pnl'] or 0)
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(abs(pnl))

    total = len(wins) + len(losses)
    wr = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 1
    b = avg_win / avg_loss if avg_loss > 0 else 0
    p = len(wins) / total if total > 0 else 0
    kelly = max(0.0, (p*b - (1-p)) / b) if b > 0 else 0

    return {
        'wr': round(wr, 2),
        'kelly': round(kelly, 4),
        'total': total,
        'wins': len(wins),
        'losses': len(losses),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
    }

def is_promoted(address: str) -> bool:
    """Kiểm tra wallet đã có trong wallet_snapshots với ts mới nhất không"""
    # Lấy ts mới nhất có nhiều wallets
    ts_row = q("SELECT MAX(ts) as max_ts FROM (SELECT ts, COUNT(*) as cnt FROM wallet_snapshots GROUP BY ts HAVING cnt >= 5)")[0]
    if not ts_row or not ts_row['max_ts']:
        return False, None
    latest_ts = ts_row['max_ts']
    r = q("SELECT 1 FROM wallet_snapshots WHERE address = ? AND ts = ?", (address, latest_ts))
    return len(r) > 0, latest_ts

def main():
    print("🔍 Enriching specialist whales with categories & performance...\n")

    # Load specialist list từ script trước
    try:
        with open('/tmp/specialist_whales_ALL.json', 'r') as f:
            specialists = json.load(f)
    except FileNotFoundError:
        print("Error: specialist_whales_ALL.json not found. Run find_specialist_whales3.py first.")
        return

    print(f"Loaded {len(specialists)} specialist wallets\n")

    enriched = []
    for s in specialists:
        addr = s['address']

        # Get top markets with categories
        top_markets_sql = """
        SELECT market_id, COUNT(*) as cnt, AVG(usdc_size) as avg
        FROM whale_trades
        WHERE address = ?
        GROUP BY market_id
        ORDER BY cnt DESC, avg DESC
        LIMIT 3
        """
        markets_raw = q(top_markets_sql, (addr,))
        market_info = []
        categories = Counter()
        for m in markets_raw:
            cat, ques = get_market_category(m['market_id'])
            categories[cat] += m['cnt']
            market_info.append({
                'condition_id': m['market_id'],
                'question': ques,
                'category': cat,
                'trades': int(m['cnt']),
                'avg_size': round(m['avg'], 2)
            })

        # Performance từ closed_positions
        perf = compute_performance_from_closed(addr)

        # Check promoted?
        promoted, snap_ts = is_promoted(addr)

        enriched.append({
            **s,
            'markets': market_info,
            'primary_category': categories.most_common(1)[0][0] if categories else 'Unknown',
            'performance': perf,
            'promoted': promoted,
            'snapshot_ts': snap_ts,
        })

    # Print enriched results
    print("="*80)
    print("SPECIALIST WHALES - ENRICHED REPORT")
    print("="*80)

    for i, w in enumerate(enriched, 1):
        print(f"\n{i}. {w['address']}")
        print(f"   Trade size: ${w['avg_size_usd']:,.0f} | Trades: {w['total_trades']} | Markets: {w['market_diversity']}")
        print(f"   Primary category: {w['primary_category']}")
        print(f"   Performance: WR={w['performance']['wr']:.1f}% ({w['performance']['wins']}/{w['performance']['total']}), Kelly={w['performance']['kelly']:.4f}")
        print(f"   Promoted: {'✅ YES (ts='+str(w['snapshot_ts'])+')' if w['promoted'] else '❌ NO'}")
        print(f"   Markets:")
        for m in w['markets']:
            print(f"     • {m['category']}: {m['question']} ({m['trades']} trades, avg ${m['avg_size']:,.0f})")

    # Summary stats
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    promoted_cnt = sum(1 for w in enriched if w['promoted'])
    print(f"Total specialist whales: {len(enriched)}")
    print(f"Already promoted: {promoted_cnt} / {len(enriched)}")
    print(f"By primary category:")
    cat_counts = Counter(w['primary_category'] for w in enriched)
    for cat, cnt in cat_counts.most_common():
        print(f"  {cat}: {cnt}")

    # Which ones NOT promoted but should be?
    not_promoted = [w for w in enriched if not w['promoted']]
    if not_promoted:
        print(f"\n⚠️  NOT PROMOTED (but meet size/specialization criteria):")
        for w in not_promoted:
            print(f"  {w['address']} - avg ${w['avg_size_usd']:,.0f}, WR={w['performance']['wr']:.1f}%")
        print(f"\n→ Consider adding these to wallet.md manually or adjusting filter to include large specialists.")

    # Save enriched
    out_file = Path('/tmp/specialist_whales_ENRICHED.json')
    out_file.write_text(json.dumps(enriched, indent=2))
    print(f"\n📁 Enriched data saved to {out_file}")
    print("✅ Done.")

if __name__ == "__main__":
    main()
