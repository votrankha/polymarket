#!/usr/bin/env python3
"""
AGENT 2 SIMULATION — Profitability Backtest

Mô phỏng copy trade từ specialists với scaling hợp lý.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import csv

DB = Path("/root/polymarket/shared/db/polybot.db")
WALLET_MD = Path("/root/polymarket/agent2_copy_trader/wallet.md")
OUT_DIR = Path("/root/polymarket/analysis/simulations")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def load_manual_wallets():
    wallets = []
    in_manual = False
    with open(WALLET_MD) as f:
        for line in f:
            line = line.strip()
            if line.startswith("## Manual Wallets"):
                in_manual = True
                continue
            if line.startswith("## ") and in_manual:
                break
            if in_manual and line and not line.startswith("#"):
                parts = line.split("|")
                if len(parts) >= 3:
                    addr = parts[0].strip()
                    try:
                        budget = float(parts[1].strip())
                    except:
                        budget = 0
                    category = parts[2].strip().lower()
                    note = parts[3].strip() if len(parts) > 3 else ""
                    if addr and budget > 0:
                        wallets.append({
                            "address": addr,
                            "budget_usdc": budget,
                            "category": category,
                            "note": note
                        })
    return wallets

def get_specialist_stats(address: str):
    """Lấy avg_size, total_trades từ whale_trades; win_rate, kelly từ wallet_snapshots"""
    sql_trades = """
    SELECT AVG(usdc_size) as avg_size, COUNT(*) as total_trades
    FROM whale_trades
    WHERE address = ?
    """
    trades_row = q(sql_trades, (address,))[0] if q(sql_trades, (address,)) else {}
    
    sql_snapshot = """
    SELECT win_rate, kelly
    FROM wallet_snapshots
    WHERE address = ?
    ORDER BY ts DESC LIMIT 1
    """
    snapshot = q(sql_snapshot, (address,))
    snap = dict(snapshot[0]) if snapshot else {}
    
    return {
        "avg_size": trades_row.get('avg_size', 0) or 0,
        "total_trades": trades_row.get('total_trades', 0) or 0,
        "win_rate": snap.get('win_rate', 0),
        "kelly": snap.get('kelly', 0)
    }

def get_specialist_closed_positions(address: str):
    """Lấy tất cả closed_positions"""
    sql = """
    SELECT market_id, outcome, realized_pnl, resolved_at, invested
    FROM closed_positions
    WHERE address = ?
    ORDER BY resolved_at ASC
    """
    return q(sql, (address,))

def main():
    print("🧪 AGENT 2 SIMULATION — Profitability Backtest")
    print("="*80)
    
    manual_wallets = load_manual_wallets()
    print(f"📋 Manual Wallets: {len(manual_wallets)}")
    for w in manual_wallets:
        print(f"  {w['address'][:12]}... | ${w['budget_usdc']} | {w['category']}")
    
    total_pnl = 0.0
    total_budget_allocated = 0.0
    wins = 0
    losses = 0
    win_pnls = []
    loss_pnls = []
    specialist_metrics = []
    
    print("\n📊 Simulating...")
    for wallet in manual_wallets:
        addr = wallet['address']
        stats = get_specialist_stats(addr)
        positions = get_specialist_closed_positions(addr)
        
        if not positions:
            print(f"  ⚠️  {addr[:12]}... no closed positions (skip)")
            continue
        
        # Lấy avg_size và total_trades để ước lượng total capital đã dùng
        avg_size = stats.get('avg_size', 0)
        total_trades = stats.get('total_trades', 0)
        estimated_total_capital = avg_size * total_trades  # rough estimate
        
        # Scaling factor: nếu specialist dùng estimated_total_capital, ta dùng budget của mình
        # scaling = min(1, budget / estimated_total_capital) nếu estimated_total_capital > 0
        # Nếu estimated_total_capital = 0, scaling = 1 (copy full P&L — optimistic)
        if estimated_total_capital > 0:
            scaling = min(1.0, wallet['budget_usdc'] / estimated_total_capital)
        else:
            scaling = 1.0
        
        # Calculate scaled P&L
        pos_pnl = sum(p['realized_pnl'] for p in positions)
        scaled_pnl = pos_pnl * scaling
        
        # Count wins/losses
        pos_wins = sum(1 for p in positions if p['realized_pnl'] > 0)
        pos_losses = sum(1 for p in positions if p['realized_pnl'] < 0)
        
        # Collect individual P&Ls for drawdown calc
        for p in positions:
            copy_pnl = p['realized_pnl'] * scaling
            if copy_pnl > 0:
                win_pnls.append(copy_pnl)
            elif copy_pnl < 0:
                loss_pnls.append(abs(copy_pnl))
        
        wins += pos_wins
        losses += pos_losses
        
        total_pnl += scaled_pnl
        total_budget_allocated += wallet['budget_usdc']
        
        specialist_metrics.append({
            "address": addr,
            "closed_positions": len(positions),
            "estimated_total_capital": estimated_total_capital,
            "scaling_factor": scaling,
            "raw_pnl": pos_pnl,
            "scaled_pnl": scaled_pnl,
            "win_rate": stats.get('win_rate', 0),
            "kelly": stats.get('kelly', 0),
            "budget": wallet['budget_usdc']
        })
        
        print(f"  {addr[:12]}... | {len(positions)} pos | raw ${pos_pnl:+.0f} | scaling={scaling:.2f}x → ${scaled_pnl:+.0f}")
    
    total_trades = wins + losses
    overall_wr = wins / total_trades * 100 if total_trades > 0 else 0
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # Max drawdown from worst consecutive losses
    all_losses = sorted(loss_pnls, reverse=True)
    top5_sum = sum(all_losses[:5])
    max_drawdown_pct = (top5_sum / total_budget_allocated * 100) if total_budget_allocated > 0 else 0
    
    print("\n" + "="*80)
    print("📈 SIMULATION RESULTS")
    print("="*80)
    print(f"Specialists simulated: {len(specialist_metrics)}")
    print(f"Total positions: {total_trades}")
    print(f"Overall Win Rate: {overall_wr:.1f}% ({wins}/{total_trades})")
    print(f"Average Win: ${avg_win:,.0f}")
    print(f"Average Loss: ${avg_loss:,.0f}")
    print(f"Win/Loss Ratio: {win_loss_ratio:.2f}")
    print(f"Total Budget: ${total_budget_allocated:,.0f}")
    print(f"Total P&L: ${total_pnl:+,.0f}")
    print(f"ROI: {(total_pnl/total_budget_allocated*100):+.1f}%")
    print(f"Est. Max Drawdown: {max_drawdown_pct:.1f}% (worst 5 losses)")
    
    proceed = total_pnl > 0 and max_drawdown_pct < 30
    print("\n💡 DECISION:")
    if proceed:
        print("  ✅ PROFITABLE — READY FOR REAL TRADING")
    else:
        print("  ❌ NOT PROFITABLE — NEED ADJUSTMENTS")
        if total_pnl <= 0:
            print("     → Total P&L <= 0")
        if max_drawdown_pct >= 30:
            print(f"     → Max drawdown {max_drawdown_pct:.1f}% >= 30%")
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "specialist_count": len(specialist_metrics),
        "total_positions": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": overall_wr,
        "avg_win_usdc": avg_win,
        "avg_loss_usdc": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "total_budget_usdc": total_budget_allocated,
        "total_pnl_usdc": total_pnl,
        "roi_pct": (total_pnl/total_budget_allocated*100) if total_budget_allocated>0 else 0,
        "max_drawdown_pct": max_drawdown_pct,
        "proceed_to_real": proceed,
        "specialist_details": specialist_metrics
    }
    
    out_file = OUT_DIR / f"simulation_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_file.write_text(json.dumps(report, indent=2))
    print(f"\n📁 Report: {out_file}")
    print("✅ Simulation complete.")
    
    return proceed, report

if __name__ == "__main__":
    main()
