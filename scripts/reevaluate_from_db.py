#!/usr/bin/env python3
"""
Recompute wallet stats from raw trade/position data in the database,
then evaluate against current filter_rules.
"""
import sqlite3
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "shared" / "db" / "polybot.db"

from agent1_whale_hunter.filter_rules import evaluate

def get_wallets_with_data():
    """Lấy danh sách wallets có ít nhất 1 trade hoặc 1 closed position."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT address FROM (
            SELECT address FROM whale_trades
            UNION
            SELECT address FROM closed_positions
        )
    """)
    return [row['address'] for row in cur.fetchall()]

def get_wallet_trades(conn, address):
    cur = conn.cursor()
    cur.execute("""
        SELECT tx_hash, side, usdc_size, shares, price, ts as timestamp, market_id as market
        FROM whale_trades
        WHERE address = ?
    """, (address,))
    return [dict(row) for row in cur.fetchall()]

def get_wallet_closed(conn, address):
    cur = conn.cursor()
    cur.execute("""
        SELECT realized_pnl as realizedPnl, outcome, market_id as market_id, resolved_at
        FROM closed_positions
        WHERE address = ?
    """, (address,))
    return [dict(row) for row in cur.fetchall()]

def compute_stats(address, trades, closed):
    now_ts = int(datetime.now(timezone.utc).timestamp())
    # Reuse analyze_history logic from agent1_whale_hunter.py
    total_vol = 0.0
    all_ts = []
    all_sizes = []
    mkt_ids = set()

    for t in trades:
        usdc = float(t.get('usdc_size', 0) or 0)
        shares = float(t.get('shares', 0) or 0)
        price = float(t.get('price', 0) or 0)
        # usdc_size is already USDC, if zero fallback to shares*price
        if usdc <= 0:
            usdc = shares * price
        if usdc <= 0:
            continue
        total_vol += usdc
        ts_raw = int(t.get('timestamp', 0) or t.get('ts', 0) or 0)
        # Normalize to seconds if appears to be milliseconds (>1e12)
        if ts_raw > 1e12:
            ts_raw = ts_raw // 1000
        if ts_raw:
            all_ts.append(ts_raw)
        mkt = t.get('market', '')
        if mkt:
            mkt_ids.add(mkt)

    n_trades = len(trades)
    if all_ts:
        first_ts = min(all_ts)
        account_age_days = max(1, (now_ts - first_ts) // 86400)
    else:
        account_age_days = 1

    months = max(1.0, account_age_days / 30.0)
    trades_per_month = n_trades / months
    avg_size = total_vol / n_trades if n_trades > 0 else 0.0

    # Closed positions
    wins = losses = 0
    win_pnls = []
    loss_pnls = []
    net_pnl = 0.0
    for pos in closed:
        pnl = float(pos.get('realizedPnl', 0) or 0)
        net_pnl += pnl
        if pnl >= 0:
            wins += 1
            win_pnls.append(pnl)
        else:
            losses += 1
            loss_pnls.append(abs(pnl))
        mkt_id = pos.get('market_id', '')
        if mkt_id:
            mkt_ids.add(mkt_id)
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

    # Kelly
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 1.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 1.0
    b = avg_win / avg_loss if avg_loss > 0 else 1.0
    p = win_rate / 100
    kelly = max(0.0, (p * b - (1 - p)) / b) if b > 0 else 0.0

    # Bot detection (simplified to match analyze_history thresholds)
    bot_round = False
    round_size_ratio = None
    if all_sizes:
        round_n = sum(1 for s in all_sizes if round(s) % 100 == 0)
        round_size_ratio = round_n / len(all_sizes)
        bot_round = round_size_ratio > 0.98

    bot_interval = None
    if len(all_ts) >= 10:
        ts_sorted = sorted(all_ts)
        ivs = [ts_sorted[i+1] - ts_sorted[i] for i in range(len(ts_sorted)-1) if ts_sorted[i+1] > ts_sorted[i]]
        if len(ivs) >= 5:
            mu = sum(ivs) / len(ivs)
            std = (sum((x - mu)**2 for x in ivs) / len(ivs))**0.5
            bot_interval = (mu > 0 and std / mu < 0.30)

    bot_hf = trades_per_month > 300
    bot_flag = bot_round or (bot_interval if bot_interval is not None else False) or bot_hf

    stats_out = {
        'win_rate': round(win_rate, 2),
        'total_trades': n_trades,
        'total_closed': total_closed,
        'net_pnl': round(net_pnl, 2),
        'total_volume': round(total_vol, 2),
        'avg_size': round(avg_size, 2),
        'trades_per_month': round(trades_per_month, 2),
        'account_age_days': account_age_days,
        'kelly': round(kelly, 4),
        'market_count': len(mkt_ids),
        'bot_flag': bot_flag,
        'interval_cv': bot_interval,
        'round_size_ratio': round_size_ratio,
    }
    return stats_out

# Main
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
addresses = get_wallets_with_data()
print(f"Total addresses with any data: {len(addresses)}")

passed = []
failed = {}

debug_count = 0
for addr in addresses:
    trades = get_wallet_trades(conn, addr)
    closed = get_wallet_closed(conn, addr)
    stats = compute_stats(addr, trades, closed)
    passed_flag, reason = evaluate(stats)
    if passed_flag:
        passed.append((addr, stats, reason))
    else:
        failed[addr] = reason

    if debug_count < 5 and stats.get('bot_flag'):
        print(f"\nDEBUG {addr[:10]} WR={stats['win_rate']}% closed={stats['total_closed']} age={stats['account_age_days']}")
        print(f"  bot_interval={stats['interval_cv']} bot_round={stats['round_size_ratio']} hf={stats['trades_per_month']}")
        debug_count += 1

conn.close()

print(f"\nPassed: {len(passed)} | Failed: {len(failed)}")
from collections import Counter
fail_counts = Counter(failed.values())
print("\nTop discard reasons:")
for reason, cnt in fail_counts.most_common(10):
    print(f"  {reason}: {cnt}")

# Calculate scores for passed wallets
from agent1_whale_hunter.filter_rules import score as filter_score
passed_with_score = []
for addr, stats, reason in passed:
    try:
        s = filter_score(stats)
    except Exception:
        s = 0.5
    passed_with_score.append((addr, stats, s, reason))

# Save to JSON for inspection
OUT = ROOT / "scripts" / "passed_wallets.json"
with open(OUT, 'w') as f:
    json.dump([{'address': a, 'stats': s, 'score': sc, 'reason': r} for a, s, sc, r in passed_with_score], f, indent=2)
print(f"\nSaved passed wallets to {OUT}")

# Generate wallet.md entries
lines = []
for addr, stats, score_val, reason in passed_with_score:
    specialist = (reason == "SPECIALIST")
    budget = 200 if specialist else 50
    category = "all"
    wr = stats['win_rate']
    kelly = stats['kelly']
    note = f"score={score_val:.3f} wr={wr:.1f}% kelly={kelly:.3f}"
    if specialist:
        note = "SPECIALIST " + note
    lines.append(f"{addr.lower()} | {budget} | {category} | {note}")

# Sort by score descending
lines.sort(key=lambda x: float(x.split('|')[3].split('wr=')[1].split('%')[0]) if 'wr=' in x else 0, reverse=True)

# Update wallet.md
WALLET_MD = ROOT / "agent2_copy_trader" / "wallet.md"
md_template = WALLET_MD.read_text(encoding="utf-8") if WALLET_MD.exists() else ""
if "## Active Wallets" in md_template:
    before, _ = md_template.split("## Active Wallets", 1)
    after = ""
else:
    before = md_template
    after = ""

new_active_header = "\n## Active Wallets\n"
new_body = "\n".join(lines)
new_md = before + new_active_header + new_body + "\n"

if WALLET_MD.exists():
    backup = WALLET_MD.with_suffix(".md.bak")
    WALLET_MD.rename(backup)
WALLET_MD.write_text(new_md, encoding="utf-8")
print(f"\n✅ Updated wallet.md with {len(lines)} active wallets")
print(f"Specialists: {sum(1 for l in lines if 'SPECIALIST' in l)}")


print(f"\nPassed: {len(passed)} | Failed: {len(failed)}")
from collections import Counter
fail_counts = Counter(failed.values())
print("\nTop discard reasons:")
for reason, cnt in fail_counts.most_common(10):
    print(f"  {reason}: {cnt}")

# Print details of passed wallets
if passed:
    print("\nPassed wallets:")
    for addr, stats, reason in passed:
        print(f"{addr[:10]}... WR={stats['win_rate']}% closed={stats['total_closed']} markets={stats['market_count']} kelly={stats['kelly']}")
