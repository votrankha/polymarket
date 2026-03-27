#!/usr/bin/env python3
"""
PHÂN TÍCH WALLET CHẤT LƯỢNG - VERIFIED
Mục tiêu: Đánh giá filter_rules có chọn đúng wallet có thể copy trade sinh lời không?
Phương pháp:
- Lấy snapshot từ wallet_snapshots (reported metrics)
- Lấy thực tế từ closed_positions (tính win rate, Kelly, avg win/loss)
- Lấy trade pattern từ whale_trades (bot detection, market diversity)
So sánh reported vs factual → tìm sai lệch
"""
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def get_latest_ts():
    res = q("SELECT MAX(ts) as ts FROM wallet_snapshots")
    return res[0]['ts']

def get_top_wallets(limit=15):
    ts = get_latest_ts()
    sql = """
    SELECT address, score, win_rate, kelly, net_pnl, avg_size, account_age_days,
           total_volume, trades_per_month, total_closed, bot_flag, source
    FROM wallet_snapshots
    WHERE ts = ?
    ORDER BY score DESC
    LIMIT ?
    """
    return q(sql, (ts, limit))

def get_closed_positions(address: str) -> List[dict]:
    sql = "SELECT * FROM closed_positions WHERE address = ?"
    return q(sql, (address,))

def get_whale_trades(address: str) -> List[dict]:
    sql = "SELECT * FROM whale_trades WHERE address = ? ORDER BY ts ASC"
    return q(sql, (address,))

def compute_from_closed(closed: List[dict]) -> Tuple[float, float, float, float]:
    """Tính win_rate, kelly, avg_win, avg_loss từ closed_positions"""
    if not closed:
        return 0.0, 0.0, 0.0, 0.0
    wins = []
    losses = []
    for p in closed:
        pnl = float(p.get('realized_pnl', 0) or 0)
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(abs(pnl))
        # Ignore zero PnL (break-even, rare)
    total = len(wins) + len(losses)
    wr = len(wins) / total * 100 if total > 0 else 0.0
    # Kelly: f* = (p*b - q) / b; b = avg_win/avg_loss
    avg_win = sum(wins)/len(wins) if wins else 0.0
    avg_loss = sum(losses)/len(losses) if losses else 1.0
    b = avg_win / avg_loss if avg_loss > 0 else 0.0
    p = len(wins) / total if total > 0 else 0.0
    kelly = max(0.0, (p*b - (1-p)) / b) if b > 0 else 0.0
    return round(wr, 2), round(kelly, 4), round(avg_win, 2), round(avg_loss, 2)

def analyze_trade_pattern(trades: List[dict]) -> Dict:
    """Bot detection metrics từ whale_trades"""
    if not trades:
        return {}
    times = [t['ts'] for t in trades if t.get('ts')]
    sizes = [t['usdc_size'] for t in trades if t.get('usdc_size')]
    avg_size = sum(sizes)/len(sizes) if sizes else 0
    avg_per_market = {}
    for t in trades:
        mkt = t.get('market_id', '')
        if mkt:
            avg_per_market.setdefault(mkt, {'count':0, 'sum':0.0})
            avg_per_market[mkt]['count'] += 1
            avg_per_market[mkt]['sum'] += float(t.get('usdc_size',0))
    diversity = len(avg_per_market)
    avg_trades_per_market = len(trades) / diversity if diversity else 0
    # Round size detection
    round_ratio = 0
    if sizes:
        round_count = sum(1 for s in sizes if abs(s % 100) < 0.01)
        round_ratio = round_count / len(sizes)
    # Time CV
    if len(times) >= 2:
        times_sorted = sorted(times)
        ivs = [times_sorted[i+1]-times_sorted[i] for i in range(len(times_sorted)-1)]
        avg_iv = sum(ivs)/len(ivs)
        std_iv = (sum((x-avg_iv)**2 for x in ivs)/len(ivs))**0.5 if ivs else 0
        iv_cv = std_iv/avg_iv if avg_iv>0 else 0
        intervals_cv = round(iv_cv, 3)
    else:
        intervals_cv = 0
    # Hour concentration (latency sniper proxy)
    hour_counts = Counter()
    for ts in times:
        hour = (ts % 86400) // 3600
        hour_counts[hour] += 1
    total = len(times)
    top3 = sum(sorted(hour_counts.values(), reverse=True)[:3])
    hour_concentration = top3/total if total else 0
    return {
        "n_trades": len(trades),
        "avg_size": avg_size,
        "round_ratio": round_ratio,
        "interval_cv": intervals_cv,
        "hour_concentration": hour_concentration,
        "market_diversity": diversity,
        "avg_trades_per_market": avg_trades_per_market,
        "timespan_days": (max(times)-min(times))/86400 if times else 0,
    }

def evaluate_bot(pattern: Dict, trades_per_month: float) -> bool:
    """Đánh giá có phải bot dựa trên pattern"""
    flags = []
    if pattern.get('round_ratio',0) > 0.9:
        flags.append("round_sizes")
    if pattern.get('interval_cv',1) < 0.1 and pattern.get('n_trades',0) >= 10:
        flags.append("regular_interval")
    if trades_per_month > 100:
        flags.append("high_freq")
    if pattern.get('hour_concentration',0) > 0.7:
        flags.append("latency_sniper")
    if pattern.get('avg_size',0) < 5 and trades_per_month > 200:
        flags.append("micro_trades")
    return len(flags) > 0

def main():
    top = get_top_wallets(15)
    print(f"🔍 Analyzing {len(top)} top wallets from DB (snapshot ts={get_latest_ts()})")

    results = []
    for w in top:
        addr = w['address']
        # Lấy closed_positions (thực tế)
        closed = get_closed_positions(addr)
        trades = get_whale_trades(addr)

        factual_wr, factual_kelly, avg_win, avg_loss = compute_from_closed(closed)
        pattern = analyze_trade_pattern(trades)

        # Bot detection thực tế
        bot_actual = evaluate_bot(pattern, w.get('trades_per_month',0))
        bot_db = bool(w.get('bot_flag',0))

        # Issues
        issues = []
        wr_diff = abs(w['win_rate'] - factual_wr) if w['win_rate'] else 0
        if wr_diff > 5.0:
            issues.append(f"WR mismatch +{wr_diff:.1f}%")
        kelly_diff = abs(w['kelly'] - factual_kelly) if w['kelly'] else 0
        if kelly_diff > 0.05:
            issues.append(f"Kelly mismatch +{kelly_diff:.3f}")
        if bot_actual != bot_db:
            issues.append(f"bot_flag={bot_db} should={bot_actual}")
        if pattern.get('market_diversity',0) < 5:
            issues.append("low_market_div")
        if pattern.get('avg_trades_per_market',0) > 15:
            issues.append(f"overtrade (avg={pattern['avg_trades_per_market']:.1f})")
        if factual_wr > 90 and pattern.get('n_trades',0) < 50:
            issues.append("suspicious_high_wr_small_sample")
        if pattern.get('round_ratio',0) > 0.8:
            issues.append("round_sizes pattern")
        if pattern.get('interval_cv',1) < 0.1:
            issues.append("regular_intervals")

        results.append({
            "address": addr,
            "score": w['score'],
            "reported": {"wr": w['win_rate'], "kelly": w['kelly'], "net_pnl": w['net_pnl']},
            "factual": {"wr": factual_wr, "kelly": factual_kelly, "avg_win": avg_win, "avg_loss": avg_loss},
            "trades_count": len(trades),
            "closed_count": len(closed),
            "pattern": pattern,
            "bot_actual": bot_actual,
            "bot_db": bot_db,
            "issues": issues,
        })

        print(f"\n{'='*80}")
        print(f"Wallet: {addr}")
        print(f"Score: {w['score']:.2f} | Reported: WR={w['win_rate']:.1f}%, Kelly={w['kelly']:.4f}")
        print(f"Factual: WR={factual_wr:.1f}% ({len([p for p in closed if float(p.get('realized_pnl',0))>=0])}/{len(closed)}), Kelly={factual_kelly:.4f}")
        print(f"Trades: {len(trades)} | Closed: {len(closed)} | Markets: {pattern.get('market_diversity',0)}")
        print(f"Pattern: round={pattern.get('round_ratio',0):.1%}, iv_cv={pattern.get('interval_cv',0):.3f}, hour_conc={pattern.get('hour_concentration',0):.1%}")
        print(f"Bot actual: {bot_actual} | DB: {bot_db}")
        if issues:
            print(f"🚩 Issues: {', '.join(issues)}")
        else:
            print("✅ No issues")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    issue_counts = Counter()
    for r in results:
        for i in r['issues']:
            issue_counts[i] += 1

    print("\n📊 Issue frequency:")
    for issue, cnt in issue_counts.most_common():
        print(f"  {issue}: {cnt} wallets ({cnt/len(results)*100:.0f}%)")

    # Recommendations
    print("\n🔧 FILTER_RULES IMPROVEMENT RECOMMENDATIONS:")
    recs = []

    # 1. WR/Kelly mismatch
    mismatch_rate = sum(1 for r in results if "WR mismatch" in r['issues']) / len(results)
    if mismatch_rate > 0.5:
        recs.append(f"CRITICAL: {mismatch_rate*100:.0f}% wallets have WR mismatch >5%. Ensure filter_rules uses /closed-positions (realizedPnl) NOT trades. Check API response mapping (realized_pnl column name).")
    else:
        recs.append("✓ WR/Kelly calculations appear accurate")

    # 2. Bot flag accuracy
    bot_wrong = sum(1 for r in results if r['bot_actual'] != r['bot_db'])
    if bot_wrong > len(results)*0.3:
        recs.append(f"IMPROVE: {bot_wrong} wallets bot_flag mismatch. Enhance bot detection: add round_sizes({pattern.get('round_ratio')}), interval CV, hour_concentration.")
    else:
        recs.append("✓ Bot detection working reasonably")

    # 3. Market diversity
    low_div = sum(1 for r in results if r['pattern'].get('market_diversity',0) < 5)
    if low_div > len(results)*0.3:
        recs.append(f"FILTER: Add min_market_diversity >= 5 to avoid overtrading few markets")
    else:
        recs.append("✓ Market diversity OK")

    # 4. Overtrading same markets
    overtrade = sum(1 for r in results if r['pattern'].get('avg_trades_per_market',0) > 15)
    if overtrade > len(results)*0.2:
        recs.append(f"FILTER: Add max_avg_trades_per_market <= 15 to prevent manipulation")
    else:
        recs.append("✓ Trade distribution OK")

    # 5. Sample size
    small_sample = sum(1 for r in results if r['closed_count'] < 30)
    if small_sample > len(results)*0.3:
        recs.append(f"FILTER: Require min_closed_positions >= 30 to reduce variance/noise")
    else:
        recs.append("✓ Sample sizes adequate")

    # 6. Suspicious high WR
    sus_high_wr = sum(1 for r in results if r['factual']['wr'] > 90 and r['closed_count'] < 50)
    if sus_high_wr > 0:
        recs.append(f"FILTER: Flag wallets with WR>90% and closed<50 as SUSPICIOUS (small-sample luck)")

    for r in recs:
        print(f"  • {r}")

    print("\n📁 Saving detailed results to /tmp/wallet_analysis_VERIFIED.json ...")
    import json
    with open('/tmp/wallet_analysis_VERIFIED.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("✅ Done.")

if __name__ == "__main__":
    main()
