#!/usr/bin/env python3
"""
Generate wallet.md Active Wallets from fresh DB evaluation (reevaluate_from_db output)
"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
WALLET_MD = ROOT / "agent2_copy_trader" / "wallet.md"

# Load stats_sample.json từ bước trước (hoặc chạy lại reevaluate_from_db lưu file)
SAMPLE_FILE = ROOT / "scripts" / "stats_sample.json"
# Nhưng sample chỉ 200, không đủ. Tôi sẽ chạy lại evaluate toàn bộ và lọc pass.

# Tuy nhiên, tôi đã có kết quả pass từ script trước (236 wallets). Tôi sẽ lưu nó vào file.
# Cập nhật: tạo script ngắn chỉ in ra các wallet pass với score.

import sys
sys.path.insert(0, str(ROOT))
from agent1_whale_hunter.filter_rules import evaluate as filter_evaluate, score as filter_score

import sqlite3
from datetime import datetime, timezone

DB_PATH = ROOT / "shared" / "db" / "polybot.db"

def get_wallets_with_data():
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
    addrs = [row['address'] for row in cur.fetchall()]
    conn.close()
    return addrs

def get_wallet_trades(conn, address):
    cur = conn.cursor()
    cur.execute("""
        SELECT tx_hash, side, usdc_size, shares, price, ts as timestamp, market_id as market
        FROM whale_trades
        WHERE address = ?
    """, (address,))
    rows = []
    for row in cur.fetchall():
        d = dict(row)
        d['usdcSize'] = d.get('usdc_size', 0)
        d['size'] = d.get('shares', 0)
        d['timestamp'] = d.get('ts', 0)
        d['market'] = d.get('market_id', '')
        rows.append(d)
    return rows

def get_wallet_closed(conn, address):
    cur = conn.cursor()
    cur.execute("""
        SELECT realized_pnl as realizedPnl, outcome, market_id as market_id, resolved_at
        FROM closed_positions
        WHERE address = ?
    """, (address,))
    rows = []
    for row in cur.fetchall():
        d = dict(row)
        d['realizedPnl'] = d.get('realized_pnl', 0)
        d['market_id'] = d.get('market_id', '')
        rows.append(d)
    return rows

def compute_stats(address, trades, closed):
    now_ts = int(datetime.now(timezone.utc).timestamp())
    total_vol = 0.0
    all_ts = []
    all_sizes = []
    mkt_ids = set()

    for t in trades:
        usdc = float(t.get('usdcSize', 0) or 0)
        shares = float(t.get('size', 0) or 0)
        price = float(t.get('price', 0) or 0)
        if usdc <= 0:
            usdc = shares * price
        if usdc <= 0:
            continue
        total_vol += usdc
        ts_raw = int(t.get('timestamp', 0) or 0)
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

    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 1.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 1.0
    b = avg_win / avg_loss if avg_loss > 0 else 1.0
    p = win_rate / 100
    kelly = max(0.0, (p * b - (1 - p)) / b) if b > 0 else 0.0

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

    # Compute market_count properly
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT market_id) as mcnt FROM whale_trades WHERE address=?", (address,))
    row = cur.fetchone()
    mkt_cnt = row['mcnt'] if row else len(mkt_ids)

    return {
        'win_rate': round(win_rate, 2),
        'total_trades': n_trades,
        'total_closed': total_closed,
        'net_pnl': round(net_pnl, 2),
        'total_volume': round(total_vol, 2),
        'avg_size': round(avg_size, 2),
        'trades_per_month': round(trades_per_month, 2),
        'account_age_days': account_age_days,
        'kelly': round(kelly, 4),
        'market_count': mkt_cnt,
        'bot_flag': bot_flag,
        'interval_cv': bot_interval,
        'round_size_ratio': round_size_ratio,
    }

# Main
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
addresses = get_wallets_with_data()
print(f"Total addresses: {len(addresses)}")

passed = []
for addr in addresses:
    trades = get_wallet_trades(conn, addr)
    closed = get_wallet_closed(conn, addr)
    stats = compute_stats(addr, trades, closed)
    passed_flag, reason = filter_evaluate(stats)
    if passed_flag:
        # Get numeric score
        s = filter_score(stats)
        passed.append((addr, stats, s, reason))
conn.close()

print(f"Passed: {len(passed)}")
# Sort by score descending
passed.sort(key=lambda x: x[2], reverse=True)

# Build wallet.md lines
lines = []
for addr, stats, score_val, reason in passed:
    specialist = (reason == "SPECIALIST") or stats.get('specialist', 0)
    budget = 200 if specialist else 50
    category = "all"
    wr = stats['win_rate']
    kelly = stats['kelly']
    note = f"score={score_val:.3f} wr={wr:.1f}% kelly={kelly:.3f}"
    if specialist:
        note = "SPECIALIST " + note
    lines.append(f"{addr.lower()} | {budget} | {category} | {note}")

# Read existing wallet.md template
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

backup = WALLET_MD.with_suffix(".md.bak")
if WALLET_MD.exists():
    WALLET_MD.rename(backup)
WALLET_MD.write_text(new_md, encoding="utf-8")
print(f"✅ wallet.md updated with {len(lines)} wallets")
print(f"Specialists: {sum(1 for l in lines if 'SPECIALIST' in l)}")
