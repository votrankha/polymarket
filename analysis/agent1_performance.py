#!/usr/bin/env python3
"""
AGENT 1 PERFORMANCE ANALYSIS sau 24h chạy
Phân tích:
- Wallets promoted vs discarded
- Specialist detection success
- Filter effectiveness
- Suggested improvements
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
import json

DB = Path("/root/polymarket/shared/db/polybot.db")

def q(sql, params=()):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def main():
    print("🔍 AGENT 1 PERFORMANCE ANALYSIS")
    print("="*80)
    
    # Lấy ts range
    ts_range = q("SELECT MIN(ts) as min_ts, MAX(ts) as max_ts FROM wallet_snapshots")[0]
    min_ts = datetime.fromtimestamp(ts_range['min_ts'])
    max_ts = datetime.fromtimestamp(ts_range['max_ts'])
    duration_hours = (ts_range['max_ts'] - ts_range['min_ts']) / 3600
    
    print(f"📅 Data collection period: {min_ts} → {max_ts} ({duration_hours:.1f} hours)")
    
    # Total snapshots
    total_snapshots = q("SELECT COUNT(*) as cnt FROM wallet_snapshots")[0]['cnt']
    print(f"📊 Total snapshots: {total_snapshots}")
    
    # Latest batch
    latest_ts = q("SELECT MAX(ts) as ts FROM wallet_snapshots")[0]['ts']
    latest_wallets = q("SELECT COUNT(*) as cnt FROM wallet_snapshots WHERE ts = ?", (latest_ts,))[0]['cnt']
    print(f"📈 Wallets in latest snapshot: {latest_wallets}")
    
    # Specialist count
    specialists = q("SELECT COUNT(*) as cnt FROM wallet_snapshots WHERE specialist = 1")
    spec_cnt = specialists[0]['cnt'] if specialists else 0
    print(f"⭐ Specialists promoted: {spec_cnt}")
    
    # Promotions over time (by hour)
    print("\n📊 Promotions by hour:")
    hourly = q("""
        SELECT strftime('%Y-%m-%d %H:00', ts, 'unixepoch') as hour, COUNT(*) as cnt
        FROM wallet_snapshots
        WHERE specialist = 1
        GROUP BY hour
        ORDER BY hour
    """)
    for row in hourly:
        print(f"  {row['hour']}: {row['cnt']} wallets")
    
    # Source distribution (latest batch)
    print("\n📋 Source distribution (latest batch):")
    sources = q("""
        SELECT source, COUNT(*) as cnt
        FROM wallet_snapshots
        WHERE ts = ?
        GROUP BY source
    """, (latest_ts,))
    for src in sources:
        print(f"  {src['source']}: {src['cnt']}")
    
    # Bot vs regular
    print("\n🤖 Bot detection:")
    bot_stats = q("""
        SELECT bot_flag, specialist, COUNT(*) as cnt
        FROM wallet_snapshots
        WHERE ts = ?
        GROUP BY bot_flag, specialist
    """, (latest_ts,))
    for b in bot_stats:
        flag = "BOT" if b['bot_flag'] else "REGULAR"
        spec = "SPECIALIST" if b['specialist'] else ""
        print(f"  {flag} {spec}: {b['cnt']}")
    
    # Avg metrics by group
    print("\n📈 Average metrics (latest batch):")
    metrics = q("""
        SELECT 
            AVG(score) as avg_score,
            AVG(win_rate) as avg_wr,
            AVG(kelly) as avg_kelly,
            AVG(avg_size) as avg_size,
            AVG(total_volume) as avg_volume,
            AVG(account_age_days) as avg_age
        FROM wallet_snapshots
        WHERE ts = ?
    """, (latest_ts,))[0]
    print(f"  Score: {metrics['avg_score']:.3f}")
    print(f"  Win Rate: {metrics['avg_wr']:.1f}%")
    print(f"  Kelly: {metrics['avg_kelly']:.4f}")
    print(f"  Avg Size: ${metrics['avg_size']:,.0f}")
    print(f"  Avg Volume: ${metrics['avg_volume']:,.0f}")
    print(f"  Avg Age: {metrics['avg_age']:.0f} days")
    
    # Specialist metrics
    print("\n⭐ Specialist metrics (latest batch):")
    spec_metrics = q("""
        SELECT 
            AVG(score) as avg_score,
            AVG(win_rate) as avg_wr,
            AVG(kelly) as avg_kelly,
            AVG(avg_size) as avg_size,
            AVG(total_volume) as avg_volume,
            COUNT(*) as cnt
        FROM wallet_snapshots
        WHERE ts = ? AND specialist = 1
    """, (latest_ts,))
    if spec_metrics and spec_metrics[0]['cnt'] > 0:
        s = spec_metrics[0]
        print(f"  Count: {s['cnt']}")
        print(f"  Score: {s['avg_score']:.3f}")
        print(f"  Win Rate: {s['avg_wr']:.1f}%")
        print(f"  Kelly: {s['avg_kelly']:.4f}")
        print(f"  Avg Size: ${s['avg_size']:,.0f}")
        print(f"  Avg Volume: ${s['avg_volume']:,.0f}")
    
    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "collection_period_hours": duration_hours,
        "total_snapshots": total_snapshots,
        "latest_batch_count": latest_wallets,
        "specialists_promoted": spec_cnt,
        "source_distribution": [dict(r) for r in sources],
        "bot_detection": [dict(r) for r in bot_stats],
        "average_metrics": dict(metrics),
        "specialist_metrics": dict(spec_metrics[0]) if spec_metrics else {}
    }
    
    out_dir = Path("/root/polymarket/analysis/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"agent1_performance_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_file.write_text(json.dumps(report, indent=2))
    print(f"\n📁 Report saved: {out_file}")
    print("✅ Analysis complete.")

if __name__ == "__main__":
    main()
