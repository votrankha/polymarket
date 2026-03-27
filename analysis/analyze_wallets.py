#!/usr/bin/env python3
"""
Phân tích lịch sử trade của từng wallet được promoted
Đánh giá:
- Tính chính xác của win_rate/kelly
- Pattern đáng tin cậy hay may mắn
- Bot detection có bắt đúng không
- Volume consistency, market diversity
- Khuyến nghị cải thiện filter_rules
"""
import sqlite3
import json
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

DB_PATH = Path("/root/polymarket/shared/db/polybot.db")

def query(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def get_top_wallets(limit=10):
    sql = """
    SELECT address, score, win_rate, kelly, avg_size, account_age_days, total_volume, trades_per_month, total_closed, bot_flag
    FROM wallet_snapshots
    WHERE ts = (SELECT MAX(ts) FROM wallet_snapshots)
    ORDER BY score DESC
    LIMIT ?
    """
    return query(sql, (limit,))

def get_wallet_trades(address: str) -> List[dict]:
    sql = """
    SELECT * FROM whale_trades
    WHERE address = ?
    ORDER BY ts ASC
    """
    return query(sql, (address,))

def get_closed_positions(address: str) -> List[dict]:
    """closed_positions lưu PnL thực tế từ db_store"""
    # Check if closed_positions table exists
    try:
        sql = "SELECT * FROM closed_positions WHERE address = ? ORDER BY ts DESC"
        return query(sql, (address,))
    except sqlite3.OperationalError:
        return []

def analyze_trade_pattern(trades: List[dict]) -> Dict:
    """Phân tích pattern của list trades"""
    if not trades:
        return {}

    times = [t['ts'] for t in trades if t.get('ts')]
    sizes = [t['usdc_size'] for t in trades if t.get('usdc_size')]
    outcomes = [t['outcome'] for t in trades if t.get('outcome')]
    markets = [t['market_id'] for t in trades if t.get('market_id')]

    avg_size = sum(sizes)/len(sizes) if sizes else 0
    size_std = (sum((s-avg_size)**2 for s in sizes)/len(sizes))**0.5 if sizes else 0
    size_cv = size_std/avg_size if avg_size > 0 else 0

    # Intervals
    ivs = []
    for i in range(1, len(times)):
        iv = times[i] - times[i-1]
        if iv > 0:
            ivs.append(iv)
    avg_iv = sum(ivs)/len(ivs) if ivs else 0
    iv_std = (sum((x-avg_iv)**2 for x in ivs)/len(ivs))**0.5 if ivs else 0
    iv_cv = iv_std/avg_iv if avg_iv > 0 else 0

    # Round sizes
    if sizes:
        round_count = sum(1 for s in sizes if round(s) % 100 == 0)
        round_ratio = round_count / len(sizes)
    else:
        round_ratio = 0

    # Outcome distribution
    outcome_counts = Counter(outcomes)
    outcome_dist = {k: v/len(outcomes) for k, v in outcome_counts.items()} if outcomes else {}

    # Market diversity
    market_counts = Counter(markets)
    market_diversity = len(market_counts)
    avg_trades_per_market = len(trades) / market_diversity if market_diversity > 0 else 0

    return {
        "n_trades": len(trades),
        "avg_size": avg_size,
        "size_cv": size_cv,
        "round_ratio": round_ratio,
        "avg_interval_sec": avg_iv,
        "interval_cv": iv_cv,
        "outcome_dist": outcome_dist,
        "market_diversity": market_diversity,
        "avg_trades_per_market": avg_trades_per_market,
        "timespan_days": (max(times) - min(times)) / 86400 if times else 0,
    }

def compute_factual_winrate(closed_positions: List[dict]) -> Tuple[float, int, int]:
    """Tính win rate thực tế từ closed_positions (realizedPnl)"""
    if not closed_positions:
        return 0.0, 0, 0
    wins = sum(1 for p in closed_positions if float(p.get('realizedPnl', 0) or 0) >= 0)
    total = len(closed_positions)
    return (wins/total*100) if total>0 else 0.0, wins, total

def compute_kelly(closed_positions: List[dict]) -> float:
    """Tính Kelly từ closed_positions"""
    if not closed_positions:
        return 0.0
    wins = []
    losses = []
    for p in closed_positions:
        pnl = float(p.get('realizedPnl', 0) or 0)
        if pnl >= 0:
            wins.append(pnl)
        else:
            losses.append(abs(pnl))
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins)/len(wins)
    avg_loss = sum(losses)/len(losses)
    b = avg_win / avg_loss if avg_loss > 0 else 1.0
    p = len(wins) / (len(wins) + len(losses))
    kelly = max(0.0, (p*b - (1-p)) / b) if b > 0 else 0.0
    return round(kelly, 4)

def evaluate_wallet(wallet_summary: dict) -> Dict:
    """Đánh giá từng wallet về chất lượng"""
    addr = wallet_summary['address']
    print(f"\n{'='*80}\nAnalyzing: {addr}")
    print(f"Score: {wallet_summary['score']:.2f} | WR (reported): {wallet_summary['win_rate']:.1f}% | Kelly (reported): {wallet_summary['kelly']:.4f}")

    # Lấy lịch sử
    trades = get_wallet_trades(addr)
    closed = get_closed_positions(addr)
    print(f"Trades in DB: {len(trades)} | Closed positions: {len(closed)}")

    # Phân tích pattern từ trades
    pattern = analyze_trade_pattern(trades)

    # Tính win rate/kelly thực tế từ closed_positions
    factual_wr, fwins, ftotal = compute_factual_winrate(closed)
    factual_kelly = compute_kelly(closed)
    print(f"Factual WR: {factual_wr:.1f}% ({fwins}/{ftotal}) | Factual Kelly: {factual_kelly:.4f}")

    # So sánh reported vs factual
    wr_diff = abs(wallet_summary['win_rate'] - factual_wr)
    kelly_diff = abs(wallet_summary['kelly'] - factual_kelly)
    print(f"Δ WR: {wr_diff:.1f}% | Δ Kelly: {kelly_diff:.4f}")

    # Bot detection flags
    bot_indicators = []
    if pattern.get('round_ratio', 0) > 0.9:
        bot_indicators.append(f"round_sizes={pattern['round_ratio']:.2%}")
    if pattern.get('interval_cv', 1) < 0.1 and pattern.get('avg_interval_sec', 0) > 0:
        bot_indicators.append(f"regular_iv(CV={pattern['interval_cv']:.2f})")
    if wallet_summary.get('trades_per_month', 0) > 100:
        bot_indicators.append(f"hf({wallet_summary['trades_per_month']:.0f}/mo)")
    if pattern.get('size_cv', 1) < 0.1:
        bot_indicators.append(f"constant_size(CV={pattern['size_cv']:.2f})")

    bot_flag_should_be = len(bot_indicators) > 0
    print(f"Bot indicators: {', '.join(bot_indicators) if bot_indicators else 'none'}")
    print(f"DB bot_flag: {bool(wallet_summary.get('bot_flag'))} | Should be: {bot_flag_should_be}")

    # Market多样性
    print(f"Market diversity: {pattern.get('market_diversity',0)} markets | avg trades/market: {pattern.get('avg_trades_per_market',0):.1f}")

    # Timespan
    print(f"Timespan: {pattern.get('timespan_days',0):.1f} days | Age: {wallet_summary.get('account_age_days',0)} days")

    # Volume consistency
    print(f"Total volume: ${wallet_summary.get('total_volume',0):,.0f} | avg size: ${wallet_summary.get('avg_size',0):,.0f}")

    # Đánh giá tổng thể
    issues = []
    if wr_diff > 5.0:
        issues.append(f"WR mismatch >5%")
    if kelly_diff > 0.05:
        issues.append(f"Kelly mismatch >0.05")
    if bot_flag_should_be != bool(wallet_summary.get('bot_flag')):
        issues.append("bot_flag incorrect")
    if factual_wr < 60 and wallet_summary.get('score', 0) > 0.5:
        issues.append("score too high for low WR")
    if pattern.get('market_diversity', 0) < 5:
        issues.append("low market diversity (<5)")
    if pattern.get('avg_trades_per_market', 0) > 10:
        issues.append("overtrading same markets")

    print(f"\n🚩 Issues: {', '.join(issues) if issues else 'None'}")

    return {
        "address": addr,
        "score": wallet_summary['score'],
        "reported_wr": wallet_summary['win_rate'],
        "factual_wr": factual_wr,
        "reported_kelly": wallet_summary['kelly'],
        "factual_kelly": factual_kelly,
        "trades_available": len(trades),
        "closed_positions": len(closed),
        "pattern": pattern,
        "bot_indicators": bot_indicators,
        "bot_flag_actual": bot_flag_should_be,
        "bot_flag_db": bool(wallet_summary.get('bot_flag')),
        "issues": issues,
    }

def main():
    top_wallets = get_top_wallets(15)
    print(f"Found {len(top_wallets)} wallets in DB")

    results = []
    for w in top_wallets:
        try:
            res = evaluate_wallet(w)
            results.append(res)
        except Exception as e:
            print(f"Error analyzing {w['address']}: {e}")

    # Tổng kết
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    issues_count = Counter()
    for r in results:
        for issue in r['issues']:
            issues_count[issue] += 1

    print("\n📊 Issues frequency:")
    for issue, cnt in issues_count.most_common():
        print(f"  {issue}: {cnt} wallets")

    # Cải tiến đề xuất
    print("\n🔧 FILTER_RULES IMPROVEMENT SUGGESTIONS:")
    suggestions = []

    # Nếu nhiều wallet có win rate thực tế khác báo cáo
    mismatches = [r for r in results if abs(r['reported_wr'] - r['factual_wr']) > 5]
    if len(mismatches) > len(results)*0.3:
        suggestions.append("Fix win_rate calculation: ensure using /closed-positions with realizedPnl, not trades")
    else:
        suggestions.append("✓ Win rate calculation appears accurate")

    # Nếu kelly chênh lệch
    kelly_mismatch = [r for r in results if abs(r['reported_kelly'] - r['factual_kelly']) > 0.05]
    if len(kelly_mismatch) > len(results)*0.3:
        suggestions.append("Fix Kelly calculation: use avg_win/avg_loss from closed_positions, not trade prices")
    else:
        suggestions.append("✓ Kelly calculation appears accurate")

    # Bot detection
    bot_wrong = [r for r in results if r['bot_flag_actual'] != r['bot_flag_db']]
    if len(bot_wrong) > len(results)*0.2:
        suggestions.append("Improve bot detection: include round size consistency, latency sniper, micro-trade spam")
    else:
        suggestions.append("✓ Bot detection working reasonably")

    # Market diversity
    low_div = [r for r in results if r['pattern'].get('market_diversity', 0) < 5]
    if len(low_div) > len(results)*0.3:
        suggestions.append("Add filter: min_market_diversity >= 5 distinct markets")
    else:
        suggestions.append("✓ Market diversity ok")

    # Overtrading same markets
    overtrade = [r for r in results if r['pattern'].get('avg_trades_per_market', 0) > 10]
    if len(overtrade) > len(results)*0.2:
        suggestions.append("Filter: max_avg_trades_per_market <= 10 (avg) to avoid market manipulation")
    else:
        suggestions.append("✓ Trade distribution ok")

    # Win rate legitimacy
    high_wr_small_vol = [r for r in results if r['factual_wr'] > 85 and r['pattern'].get('n_trades',0) < 50]
    if high_wr_small_vol:
        suggestions.append("Flag: high win rate with small sample size (<50 closed) as suspicious")

    for s in suggestions:
        print(f"  • {s}")

    print("\n📁 Saving analysis to /tmp/wallet_analysis.json ...")
    with open('/tmp/wallet_analysis.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Done.")

if __name__ == "__main__":
    main()
