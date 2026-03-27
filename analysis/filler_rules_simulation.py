#!/usr/bin/env python3
"""
FILLER RULES SIMULATION — Determine optimal filler rules for Agent 2
"""

import argparse
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB = Path("/root/polymarket/shared/db/polybot.db")
OUT_DIR = Path("/root/polymarket/analysis/simulations")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def get_specialist_stats(address):
    # Get avg_size, total_trades, total_volume from whale_trades
    sql_trades = """
    SELECT AVG(usdc_size) as avg_size, COUNT(*) as total_trades, SUM(usdc_size) as total_volume
    FROM whale_trades
    WHERE address = ?
    """
    row = q(sql_trades, (address,))
    if row:
        tr = row[0]
    else:
        tr = {'avg_size':0, 'total_trades':0, 'total_volume':0}
    # Get win_rate, kelly from latest wallet_snapshot
    sql_snap = """
    SELECT win_rate, kelly
    FROM wallet_snapshots
    WHERE address = ?
    ORDER BY ts DESC LIMIT 1
    """
    snap_rows = q(sql_snap, (address,))
    if snap_rows:
        snap = snap_rows[0]
    else:
        snap = {'win_rate':0, 'kelly':0}
    return {
        'avg_size': tr['avg_size'] or 0,
        'total_trades': tr['total_trades'] or 0,
        'total_volume': tr['total_volume'] or 0,
        'win_rate': snap['win_rate'] or 0,
        'kelly': snap['kelly'] or 0
    }

def get_specialist_closed_positions(address):
    sql = """
    SELECT realized_pnl, invested
    FROM closed_positions
    WHERE address = ?
    """
    rows = q(sql, (address,))
    return [{'realized_pnl': r['realized_pnl'], 'invested': r['invested']} for r in rows]

def filter_specialists():
    """All wallets with specialist=1 flag"""
    sql = "SELECT DISTINCT address FROM wallet_snapshots WHERE specialist=1"
    rows = q(sql)
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            candidates.append({
                'address': addr,
                'budget_usdc': 200,
                'note': 'specialist',
                'stats': stats
            })
    return candidates

def filter_high_score(score_thresh=0.7, kelly_thresh=0.5, min_closed=10, limit=10, budget=100):
    """High scoring whales with sufficient activity"""
    max_ts = q("SELECT MAX(ts) as max_ts FROM wallet_snapshots")[0]['max_ts']
    sql = """
    SELECT ws.address, ws.score, ws.win_rate, ws.kelly, ws.total_closed
    FROM wallet_snapshots ws
    WHERE ws.ts = ? AND ws.score >= ? AND ws.kelly >= ? AND ws.total_closed >= ?
    ORDER BY ws.score DESC
    LIMIT ?
    """
    rows = q(sql, (max_ts, score_thresh, kelly_thresh, min_closed, limit))
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            candidates.append({
                'address': addr,
                'budget_usdc': budget,
                'note': f"high_score: score={r['score']:.3f}, kelly={r['kelly']:.3f}",
                'stats': stats
            })
    return candidates

def filter_category_politics(budget=150, limit=5):
    """Wallets with primary_category='politics' (or majority politics trades)"""
    max_ts = q("SELECT MAX(ts) as max_ts FROM wallet_snapshots")[0]['max_ts']
    sql = """
    SELECT address, score, primary_category
    FROM wallet_snapshots
    WHERE ts = ? AND primary_category = 'politics'
    ORDER BY score DESC
    LIMIT ?
    """
    rows = q(sql, (max_ts, limit))
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            candidates.append({
                'address': addr,
                'budget_usdc': budget,
                'note': f"politics specialist: score={r['score']:.3f}",
                'stats': stats
            })
    return candidates

def filter_category_sports(budget=150, limit=5):
    max_ts = q("SELECT MAX(ts) as max_ts FROM wallet_snapshots")[0]['max_ts']
    sql = """
    SELECT address, score, primary_category
    FROM wallet_snapshots
    WHERE ts = ? AND primary_category = 'sports'
    ORDER BY score DESC
    LIMIT ?
    """
    rows = q(sql, (max_ts, limit))
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            candidates.append({
                'address': addr,
                'budget_usdc': budget,
                'note': f"sports specialist: score={r['score']:.3f}",
                'stats': stats
            })
    return candidates

def filter_combined_high_specialists(budget=150):
    """Union of specialists and high-score whales"""
    specs = filter_specialists()
    high = filter_high_score(score_thresh=0.7, kelly_thresh=0.5, min_closed=10, limit=20, budget=budget)
    seen = set()
    combined = []
    for cand in specs + high:
        if cand['address'] not in seen:
            seen.add(cand['address'])
            combined.append(cand)
    return combined

def filter_kelly_optimized(budget_base=100, limit=15):
    """Select top by Kelly"""
    max_ts = q("SELECT MAX(ts) as max_ts FROM wallet_snapshots")[0]['max_ts']
    sql = """
    SELECT ws.address, ws.kelly, ws.score, ws.total_closed
    FROM wallet_snapshots ws
    WHERE ws.ts = ? AND ws.kelly >= 0.4 AND ws.total_closed >= 10
    ORDER BY ws.kelly DESC
    LIMIT ?
    """
    rows = q(sql, (max_ts, limit))
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            kelly = r['kelly']
            scaled_budget = max(50, min(200, kelly * budget_base))
            candidates.append({
                'address': addr,
                'budget_usdc': scaled_budget,
                'note': f"kelly_opt: kelly={kelly:.3f}, budget={scaled_budget:.0f}",
                'stats': stats
            })
    return candidates

def filter_winrate_focused(threshold=0.8, min_closed=20, kelly_min=0.4, budget=100, limit=20):
    max_ts = q("SELECT MAX(ts) as max_ts FROM wallet_snapshots")[0]['max_ts']
    sql = """
    SELECT address, score, win_rate, kelly, total_closed
    FROM wallet_snapshots
    WHERE ts = ? AND win_rate >= ? AND total_closed >= ? AND kelly >= ?
    ORDER BY win_rate DESC
    LIMIT ?
    """
    rows = q(sql, (max_ts, threshold, min_closed, kelly_min, limit))
    candidates = []
    for r in rows:
        addr = r['address']
        stats = get_specialist_stats(addr)
        if stats['total_volume'] and stats['total_volume'] > 0:
            candidates.append({
                'address': addr,
                'budget_usdc': budget,
                'note': f"winrate: wr={r['win_rate']:.1f}%, kelly={r['kelly']:.3f}",
                'stats': stats
            })
    return candidates

def simulate_candidates(candidates):
    total_pnl = 0.0
    total_budget_allocated = 0.0
    total_wins = 0
    total_positions = 0
    wallet_results = []
    
    for cand in candidates:
        addr = cand['address']
        budget = cand['budget_usdc']
        stats = cand['stats']
        positions = get_specialist_closed_positions(addr)
        if not positions:
            continue
        # Filter positions with non-None invested and realized_pnl
        valid_positions = [p for p in positions if p.get('invested') is not None and p.get('realized_pnl') is not None]
        if not valid_positions:
            continue
        total_invested = sum(p['invested'] for p in valid_positions)
        raw_pnl = sum(p['realized_pnl'] for p in valid_positions)
        # Use total_volume from stats for scaling
        total_volume = stats['total_volume']
        if total_volume and total_volume > 0:
            scaling = budget / total_volume
        else:
            scaling = 0.0
        if scaling > 1:
            scaling = 1.0
        scaled_pnl = raw_pnl * scaling
        wins = sum(1 for p in valid_positions if p['realized_pnl'] > 0)
        total_positions += len(valid_positions)
        total_wins += wins
        total_pnl += scaled_pnl
        total_budget_allocated += budget
        wallet_results.append({
            'address': addr,
            'budget': budget,
            'scaling': scaling,
            'raw_pnl': raw_pnl,
            'scaled_pnl': scaled_pnl,
            'positions': len(valid_positions),
            'wins': wins,
            'avg_size': stats['avg_size'],
            'win_rate': stats['win_rate'],
            'kelly': stats['kelly']
        })
    
    win_rate = total_wins / total_positions if total_positions > 0 else 0
    roi = (total_pnl / total_budget_allocated) * 100 if total_budget_allocated > 0 else 0
    return {
        'total_budget': total_budget_allocated,
        'total_pnl': total_pnl,
        'roi': roi,
        'win_rate': win_rate,
        'total_positions': total_positions,
        'wallets': wallet_results
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', required=True, choices=['A','B','C_politics','C_sports','D','E','F','all'], help='Scenario to run or "all" for all')
    args = parser.parse_args()
    
    scenarios = {
        'A': ('Specialists only', filter_specialists),
        'B': ('High-score whales', lambda: filter_high_score(score_thresh=0.7, kelly_thresh=0.5, min_closed=10, limit=10, budget=100)),
        'C_politics': ('Politics specialists', lambda: filter_category_politics(budget=150, limit=5)),
        'C_sports': ('Sports specialists', lambda: filter_category_sports(budget=150, limit=5)),
        'D': ('Combined (specialists+high-score)', lambda: filter_combined_high_specialists(budget=150)),
        'E': ('Kelly-optimized', lambda: filter_kelly_optimized(budget_base=100, limit=15)),
        'F': ('Win-rate focused', lambda: filter_winrate_focused(threshold=0.8, min_closed=20, kelly_min=0.4, budget=100, limit=20))
    }
    
    run_scenarios = scenarios.keys() if args.scenario == 'all' else [args.scenario]
    
    summary = {}
    for code in run_scenarios:
        name, func = scenarios[code]
        print(f"\n▶️  Scenario {code}: {name}")
        candidates = func()
        print(f"   Candidates: {len(candidates)}")
        for c in candidates[:5]:
            print(f"     - {c['address'][:12]}... budget=${c['budget_usdc']} note={c['note']}")
        if len(candidates) > 5:
            print(f"     ... and {len(candidates)-5} more")
        res = simulate_candidates(candidates)
        summary[code] = {
            'name': name,
            'candidates': len(candidates),
            'total_budget': res['total_budget'],
            'total_pnl': res['total_pnl'],
            'roi': res['roi'],
            'win_rate': res['win_rate'],
            'total_positions': res['total_positions'],
            'details': res
        }
        print(f"   ROI: {res['roi']:.1f}%, WR: {res['win_rate']*100:.1f}%, PnL: ${res['total_pnl']:.0f}, Positions: {res['total_positions']}")
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    out_path = OUT_DIR / f"filler_rules_summary_{timestamp}.json"
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n✅ Summary saved: {out_path}")
    
    print("\n📊 COMPARISON:")
    print(f"{'Scenario':<10} {'Candidates':<10} {'ROI%':<10} {'WR%':<10} {'PnL':<12} {'Positions':<10}")
    for code in run_scenarios:
        s = summary[code]
        print(f"{code:<10} {s['candidates']:<10} {s['roi']:<10.1f} {s['win_rate']*100:<10.1f} ${s['total_pnl']:<11.0f} {s['total_positions']:<10}")

if __name__ == '__main__':
    main()
