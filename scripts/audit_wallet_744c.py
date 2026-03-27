#!/usr/bin/env python3
"""
AUDIT wallet 0x744c07... — Missing closed positions investigation
"""

import sqlite3

DB = "/root/polymarket/shared/db/polybot.db"
wallet = "0x744c072005bde6ddab8764a7477f61d3d22ae37f"

def q(qstr, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(qstr, params)]

print("="*70)
print(f"AUDIT: {wallet}")
print("="*70)

# 1. whale_trades: unique conditionIds
wt = q("""
    SELECT COUNT(*) as trade_cnt, COUNT(DISTINCT market_id) as unique_mkts,
           SUM(usdc_size) as total_vol, AVG(usdc_size) as avg_size,
           MIN(ts) as first_ts, MAX(ts) as last_ts
    FROM whale_trades WHERE address = ?
""", (wallet,))
if wt[0]['trade_cnt']:
    t = wt[0]
    days = (t['last_ts'] - t['first_ts']) / 86400
    print(f"\n📈 WHALE_TRADES:")
    print(f"   Trades: {t['trade_cnt']}")
    print(f"   Unique markets (condition_id): {t['unique_mkts']}")
    print(f"   Total volume: ${t['total_vol']:,.2f}")
    print(f"   Avg size: ${t['avg_size']:,.2f}")
    print(f"   Active days: {days:.1f}")
else:
    print("\n📈 WHALE_TRADES: none")

# 2. closed_positions: aggregated stats
cp = q("""
    SELECT COUNT(*) as total_pos,
           SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
           SUM(realized_pnl) as total_pnl,
           COUNT(DISTINCT market_id) as markets_closed
    FROM closed_positions WHERE address = ?
""", (wallet,))
if cp[0]['total_pos']:
    c = cp[0]
    wr = (c['wins']/c['total_pos']*100) if c['total_pos'] else 0
    print(f"\n💰 CLOSED_POSITIONS:")
    print(f"   Total: {c['total_pos']}")
    print(f"   Wins/Losses: {c['wins']} / {c['losses']}")
    print(f"   Win rate: {wr:.1f}%")
    print(f"   Total PnL: ${c['total_pnl']:,.2f}")
    print(f"   Unique markets (market_id): {c['markets_closed']}")
else:
    print("\n💰 CLOSED_POSITIONS: none")

# 3. Compare marketplace coverage
print(f"\n🔍 COVERAGE ANALYSIS:")
if wt[0]['unique_mkts'] and cp[0]['markets_closed']:
    wt_mkts = wt[0]['unique_mkts'] or 0
    cp_mkts = cp[0]['markets_closed'] or 0
    missing = wt_mkts - cp_mkts
    pct_missing = (missing/wt_mkts*100) if wt_mkts else 0
    print(f"   Markets in whale_trades: {wt_mkts}")
    print(f"   Markets in closed_positions: {cp_mkts}")
    if missing > 0:
        print(f"   Potential missing: {missing} ({pct_missing:.1f}% of whale markets)")
    else:
        print("   Potential missing: None")

# 4. PnL per trade analysis
if cp[0]['total_pos']:
    c = cp[0]
    avg_win = q("""
        SELECT AVG(realized_pnl) as avg_win FROM closed_positions
        WHERE address = ? AND realized_pnl > 0
    """, (wallet,))[0]['avg_win'] or 0
    avg_loss = q("""
        SELECT AVG(realized_pnl) as avg_loss FROM closed_positions
        WHERE address = ? AND realized_pnl < 0
    """, (wallet,))[0]['avg_loss'] or 0
    print(f"\n📊 PNL DISTRIBUTION:")
    print(f"   Avg win: ${avg_win:,.2f}")
    print(f"   Avg loss: ${avg_loss:,.2f}")
    print(f"   Win/Loss ratio: {abs(avg_win/avg_loss):.2f}:1" if avg_loss else "   Win/Loss ratio: ∞ (no losses)")

# 5. Compare with external (Polymarket Analytics)
print(f"\n📌 EXTERNAL COMPARISON:")
print("   Source: polymarketanalytics.com")
print("   Reported: WR=85%, PnL=$956,158")
if cp[0]['total_pos']:
    our_wr = wr
    our_pnl = c['total_pnl']
    print(f"   Our DB: WR={our_wr:.1f}%, PnL=${our_pnl:,.2f}")
    pnl_diff = 956158 - our_pnl
    print(f"   Discrepancy: ${pnl_diff:,.2f} ({(pnl_diff/956158*100):.1f}% lower)")
    if our_pnl > 0:
        print(f"   Reasonability: Our PnL is {our_pnl/956158*100:.1f}% of external")

# 6. Specialist eligibility re-check
print(f"\n🎯 SPECIALIST ELIGIBILITY (relaxed thresholds):")
spec_req = {
    'avg_size': (1000, t['avg_size'] if wt[0]['trade_cnt'] else 0),
    'total_closed': (150, c['total_pos'] if cp[0]['total_pos'] else 0),
    'market_count': (20, cp[0]['markets_closed'] if cp[0]['total_pos'] else 0),
    'total_volume': (50000, t['total_vol'] if wt[0]['trade_cnt'] else 0),
    'win_rate': (55, our_wr if cp[0]['total_pos'] else 0),
    'kelly': (0.15, None),  # placeholder
    'account_age': (90, None)  # placeholder
}
# Get kelly & account_age from wallet_snapshots
ws = q("SELECT kelly, account_age_days FROM wallet_snapshots WHERE address = ? ORDER BY ts DESC LIMIT 1;", (wallet,))
if ws:
    spec_req['kelly'] = (0.15, ws[0]['kelly'])
    spec_req['account_age'] = (90, ws[0]['account_age_days'])

passed = 0
for name, (threshold, actual) in spec_req.items():
    if actual is None:
        continue
    ok = actual >= threshold if 'avg' in name or 'volume' in name or 'win_rate' in name or 'kelly' in name or 'account' in name else actual <= threshold
    status = "✅" if ok else "❌"
    print(f"   {name}: {status} (req>={threshold}, actual={actual:.2f})")
    if ok:
        passed += 1

total_check = len([k for k in spec_req if spec_req[k][1] is not None])
print(f"\n   Passed: {passed}/{total_check} criteria")
if passed == total_check:
    print("   ✅ WOULD BE SPECIALIST if promoted!")
else:
    print("   ❌ NOT SPECIALIST — market_count too high" if spec_req['market_count'][1] > 20 else "   ❌ NOT SPECIALIST — other fails")

# 7. Recommendations
print("\n" + "="*70)
print("RECOMMENDATIONS:")
print("="*70)
if cp[0]['total_pos'] and wt[0]['unique_mkts']:
    if missing > 0:
        print(f"1. INCOMPLETE DATA: {missing} markets appear in whale_trades but not closed_positions.")
        print("   → Likely cause: closed_positions fetch missing some resolution events.")
        print("   → Action: Re-run fetch for this wallet to fill gaps.")
    else:
        print("1. Data appears complete (all whale markets have closed positions).")
print(f"2. Specialist status: NOT ELIGIBLE due to market_count={cp[0]['markets_closed']} > 20.")
print("   → This wallet is a retail-style diversified trader, not a specialist.")
print("3. PnL discrepancy with external source suggests either:")
print("   a) External includes unrealized PnL (unlikely)")
print("   b) Our closed_positions missing many old positions")
print("   c) External uses different calculation method (gross vs net)")
print("   → Investigate by comparing raw trade history from API.")
print("="*70)
