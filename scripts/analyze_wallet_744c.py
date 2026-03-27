#!/usr/bin/env python3
import sqlite3
import json

DB = "/root/polymarket/shared/db/polybot.db"
wallet = "0x744c072005bde6ddab8764a7477f61d3d22ae37f"

def query(q, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(q, params)]

# 1. tracked?
with open('/root/polymarket/shared/db/tracked_wallets.json', 'r') as f:
    tracked = json.load(f)

print(f"Wallet: {wallet}")
if wallet in tracked:
    data = tracked[wallet]
    print(f"✅ tracked_wallets.json: notes='{data.get('notes','')}', specialist={data.get('specialist',False)}")
else:
    print(f"❌ Not in tracked_wallets.json")

# 2. whale_trades
trades = query("""
    SELECT COUNT(*) as cnt, SUM(usdc_size) as vol, AVG(usdc_size) as avg,
           MIN(ts) as first_ts, MAX(ts) as last_ts
    FROM whale_trades WHERE address = ?
""", (wallet,))
if trades[0]['cnt']:
    t = trades[0]
    print(f"\n📈 Whale Trades:")
    print(f"   Trades: {t['cnt']}, Volume: ${t['vol']:,.2f}, Avg: ${t['avg']:,.2f}")
    if t['first_ts']:
        days = (t['last_ts'] - t['first_ts']) / 86400
        print(f"   Active: {days:.1f} days")
else:
    print("\n📈 Whale Trades: none")

# 3. closed_positions
cp = query("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
        SUM(realized_pnl) as pnl,
        COUNT(DISTINCT market_id) as markets
    FROM closed_positions WHERE address = ?
""", (wallet,))
if cp[0]['total']:
    c = cp[0]
    wr = (c['wins']/c['total']*100) if c['total'] else 0
    print(f"\n💰 Closed Positions:")
    print(f"   Total: {c['total']}, Wins: {c['wins']}, Losses: {c['losses']}")
    print(f"   Win rate: {wr:.1f}%, PnL: ${c['pnl']:,.2f}, Markets: {c['markets']}")
else:
    print("\n💰 Closed Positions: none")

# 4. wallet_snapshots latest
ws = query("SELECT * FROM wallet_snapshots WHERE address = ? ORDER BY ts DESC LIMIT 1;", (wallet,))
if ws:
    s = ws[0]
    print(f"\n📊 Latest Snapshot:")
    for key in ['score','win_rate','kelly','avg_size','total_volume','total_closed','market_count','trades_per_month','account_age_days','bot_flag','specialist']:
        val = s.get(key, 'N/A')
        if isinstance(val, (int, float)) and key not in ['bot_flag','specialist']:
            if key in ['avg_size','total_volume','total_pnl']:
                print(f"   {key}: ${val:,.2f}")
            elif key == 'trades_per_month':
                print(f"   {key}: {val:,.1f}")
            else:
                print(f"   {key}: {val}")
        else:
            print(f"   {key}: {val}")
else:
    print("\n📊 Latest Snapshot: N/A")

# 5. Specialist check (current relaxed criteria)
spec_params = {
    'specialist_avg_size_usd': 1000,
    'specialist_total_trades': 150,
    'specialist_market_diversity': 20,
    'specialist_total_volume_usd': 50000,
    'specialist_win_rate': 55,
    'specialist_kelly': 0.15,
    'specialist_account_age_days': 90,
}
if ws:
    s = ws[0]
    checks = [
        ('avg_size', s.get('avg_size',0) >= spec_params['specialist_avg_size_usd']),
        ('total_closed', s.get('total_closed',0) <= spec_params['specialist_total_trades']),
        ('market_count', s.get('market_count',0) <= spec_params['specialist_market_diversity']),
        ('total_volume', s.get('total_volume',0) >= spec_params['specialist_total_volume_usd']),
        ('win_rate', s.get('win_rate',0) >= spec_params['specialist_win_rate']),
        ('kelly', s.get('kelly',0) >= spec_params['specialist_kelly']),
        ('account_age', s.get('account_age_days',0) >= spec_params['specialist_account_age_days']),
        ('bot_flag', s.get('bot_flag',0) == 0)
    ]
    print(f"\n🎯 Specialist Eligibility (relaxed):")
    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"   {name}: {status}")
    if all(p for _,p in checks):
        print("   → WOULD BE SPECIALIST!")
    else:
        print("   → Not specialist yet.")

print("\n" + "="*60)
print("Cross-check with Polymarket Analytics (reported):")
print("   External WR: 85%, PnL: $956,158")
if cp and cp[0]['total']:
    print(f"   Our WR: {wr:.1f}%, PnL: ${c['pnl']:,.2f}")
    diff_pnl = 956158 - (c['pnl'] if cp else 0)
    print(f"   Discrepancy PnL: ${diff_pnl:,.2f}")
else:
    print("   Our data: insufficient")
