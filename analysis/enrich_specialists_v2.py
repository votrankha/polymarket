#!/usr/bin/env python3
"""
ENRICH SPECIALIST WHALES với category inference từ question text.
Sử dụng keyword matching - không cần API credentials.
"""
import sqlite3
import json
from collections import Counter
from pathlib import Path

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def guess_category(question: str) -> str:
    """Heuristic categorization từ question text"""
    if not question:
        return "Other"
    q_low = question.lower()

    # Politics & Geopolitics
    politics_keywords = [
        'president', 'election', 'biden', 'trump', 'harris', 'vote', 'electoral',
        'ukraine', 'russia', 'ceasefire', 'war', 'nato', 'putin', 'zelensky',
        'taiwan', 'china', 'israel', 'gaza', 'middle east', 'iran',
        'senate', 'congress', 'supreme court', 'impeachment',
        'tax', 'budget', 'debt ceiling', 'government shutdown'
    ]
    for kw in politics_keywords:
        if kw in q_low:
            return "Politics/Geopolitics"

    # Crypto
    crypto_keywords = [
        'bitcoin', 'ethereum', 'solana', 'crypto', 'blockchain', 'token',
        'btc', 'eth', 'usdc', 'usdt', 'defi', 'nft', 'web3',
        'binance', 'coinbase', 'gemini', 'kraken',
        'hashrate', 'difficulty', 'halving', 'staking'
    ]
    for kw in crypto_keywords:
        if kw in q_low:
            return "Crypto"

    # Sports
    sports_keywords = [
        'nba', 'nfl', 'mlb', 'nhl', 'mls', 'fifa', 'uefa',
        'super bowl', 'world series', 'stanley cup', 'champions league',
        'tennis', 'golf', 'olympics', 'wimbledon', 'masters',
        'football', 'basketball', 'baseball', 'hockey', 'soccer',
        'draft', 'mvp', 'playoffs', 'finals', 'championship'
    ]
    for kw in sports_keywords:
        if kw in q_low:
            return "Sports"

    # Economy
    econ_keywords = [
        'inflation', 'fed', 'interest rate', 'fomc', 'gdp', 'economy',
        'recession', 'unemployment', 'jobs report', 'nonfarm',
        'consumer price', 'cpi', 'ppi', 'retail sales',
        'dow', 's&p', 'nasdaq', 'stock market', 'wall street'
    ]
    for kw in econ_keywords:
        if kw in q_low:
            return "Economy"

    # Weather/Climate
    weather_keywords = [
        'temperature', 'rain', 'snow', 'hurricane', 'storm', 'weather',
        'climate', 'el niño', 'la niña', 'drought', 'flood'
    ]
    for kw in weather_keywords:
        if kw in q_low:
            return "Weather/Climate"

    # Science/Tech
    sci_keywords = [
        'ai', 'artificial intelligence', 'machine learning', 'gpt',
        'spacex', 'nasa', 'rocket', 'mars', 'moon',
        'iphone', 'android', 'apple', 'google', 'meta',
        'quantum', 'biotech', 'vaccine', 'covid'
    ]
    for kw in sci_keywords:
        if kw in q_low:
            return "Science/Tech"

    # Entertainment
    ent_keywords = [
        'movie', 'film', 'box office', 'streaming', 'netflix',
        'oscar', 'grammy', 'emmy', 'tony',
        'album', 'artist', 'band', 'concert', 'tour',
        'actor', 'actress', 'director', 'hollywood'
    ]
    for kw in ent_keywords:
        if kw in q_low:
            return "Entertainment"

    return "Other"

def compute_factual_performance(address: str) -> dict:
    """Tính WR, Kelly từ closed_positions"""
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
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = sum(losses)/len(losses) if losses else 1
    b = avg_win / avg_loss if avg_loss > 0 else 0
    p = len(wins)/total if total > 0 else 0
    kelly = max(0.0, (p*b - (1-p))/b) if b>0 else 0

    return {
        'wr': round(wr, 2),
        'kelly': round(kelly, 4),
        'total': total,
        'wins': len(wins),
        'losses': len(losses),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2)
    }

def main():
    print("🔍 Loading specialist whales and enriching with category heuristics...\n")

    try:
        with open('/tmp/specialist_whales_ALL.json', 'r') as f:
            specialists = json.load(f)
    except FileNotFoundError:
        print("Error: specialist_whales_ALL.json not found.")
        return

    print(f"Loaded {len(specialists)} specialist wallets\n")

    enriched = []
    for s in specialists:
        addr = s['address']

        # Get top markets with questions (from whale_trades)
        top_markets_sql = """
        SELECT market_id, question, COUNT(*) as cnt, AVG(usdc_size) as avg
        FROM whale_trades
        WHERE address = ?
        GROUP BY market_id, question
        ORDER BY cnt DESC, avg DESC
        LIMIT 3
        """
        markets_raw = q(top_markets_sql, (addr,))
        market_info = []
        categories = Counter()
        for m in markets_raw:
            question = m['question'] or ''
            cat = guess_category(question)
            categories[cat] += m['cnt']
            market_info.append({
                'condition_id': m['market_id'],
                'question': question[:80],
                'category': cat,
                'trades': int(m['cnt']),
                'avg_size': round(m['avg'], 2)
            })

        # Performance từ closed_positions
        perf = compute_factual_performance(addr)

        # Check promoted? (có trong wallet_snapshots ts mới nhất, với score >= 0.5)
        promoted_sql = """
        SELECT 1 FROM wallet_snapshots
        WHERE address = ? AND ts = (SELECT MAX(ts) FROM wallet_snapshots) AND score >= 0.5
        """
        promoted = len(q(promoted_sql, (addr,))) > 0

        enriched.append({
            **s,
            'markets': market_info,
            'primary_category': categories.most_common(1)[0][0] if categories else 'Unknown',
            'secondary_categories': [cat for cat, _ in categories.most_common(2)[1:] if cat],
            'performance': perf,
            'promoted': promoted,
        })

    # Print report
    print("="*80)
    print("SPECIALIST WHALES - ENRICHED WITH CATEGORIES")
    print("="*80)

    for i, w in enumerate(enriched, 1):
        print(f"\n{i}. {w['address']}")
        print(f"   Trade size: ${w['avg_size_usd']:,.0f} | Trades: {w['total_trades']} | Markets: {w['market_diversity']}")
        print(f"   Primary category: {w['primary_category']}")
        if w['secondary_categories']:
            print(f"   Secondary: {', '.join(w['secondary_categories'])}")
        print(f"   Performance: WR={w['performance']['wr']:.1f}% ({w['performance']['wins']}/{w['performance']['total']}), Kelly={w['performance']['kelly']:.4f}")
        print(f"   Promoted: {'✅ YES' if w['promoted'] else '❌ NO'}")
        print(f"   Markets:")
        for m in w['markets']:
            print(f"     • [{m['category']}] {m['question']} ({m['trades']} trades, avg ${m['avg_size']:,.0f})")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    promoted_cnt = sum(1 for w in enriched if w['promoted'])
    print(f"Total specialist whales: {len(enriched)}")
    print(f"Already promoted: {promoted_cnt} / {len(enriched)}")
    print(f"\nBy primary category:")
    cat_counts = Counter(w['primary_category'] for w in enriched)
    for cat, cnt in cat_counts.most_common():
        print(f"  {cat}: {cnt}")

    not_promoted = [w for w in enriched if not w['promoted']]
    if not_promoted:
        print(f"\n⚠️  NOT PROMOTED (but meet size/specialization criteria):")
        for w in not_promoted:
            vol = w['total_volume_usd']
            wr = w['performance']['wr']
            print(f"  {w['address'][:12]}... avg ${w['avg_size_usd']:,.0f}, total ${vol:,.0f}, WR={wr:.1f}%")
        print("\n💡 ACTION: These should be promoted after specialist rule is added.")

    # Save
    out_file = Path('/tmp/specialist_whales_ENRICHED.json')
    out_file.write_text(json.dumps(enriched, indent=2))
    print(f"\n📁 Enriched data saved to {out_file}")
    print("✅ Done.")

if __name__ == "__main__":
    main()
