#!/usr/bin/env python3
"""
DAILY POLYMARKET RESEARCH — Market Intelligence
Collects internal stats + web insights about Polymarket.
"""

import sqlite3
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/polymarket")
DB = ROOT / "shared" / "db" / "polybot.db"
LOG = ROOT / "shared" / "agent1.log"
OUT_DIR = Path("/root/.openclaw/workspace/market_research")
OUT_DIR.mkdir(parents=True, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
out_path = OUT_DIR / f"{today}.md"

def get_internal_stats():
    stats = {}
    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM whale_trades")
        stats['total_trades'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT address) FROM wallet_snapshots")
        stats['unique_wallets'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_snapshots WHERE specialist=1")
        stats['specialists'] = cur.fetchone()[0]
        cur.execute("SELECT MAX(ts) FROM wallet_snapshots")
        ts = cur.fetchone()[0]
        if ts:
            stats['last_snapshot'] = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
        else:
            stats['last_snapshot'] = 'N/A'
        conn.close()
    except Exception as e:
        stats['error'] = str(e)
    return stats

def count_log_errors():
    err = 0
    try:
        with open(LOG) as f:
            for line in f:
                if "ERROR" in line or "Traceback" in line:
                    err += 1
    except:
        pass
    return err

def web_search(query, count=5):
    """Try to use openclaw exec web_search; fallback to empty."""
    try:
        result = subprocess.run(
            ["openclaw", "exec", "web_search", f'--query="{query}"', f'--count={count}'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    return []

def generate_report():
    stats = get_internal_stats()
    err_count = count_log_errors()
    
    lines = [
        f"# Polymarket Daily Research — {today}",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} Berlin",
        "",
        "## 📊 Internal System Statistics",
        f"- Total whale trades collected: {stats.get('total_trades','N/A')}",
        f"- Unique wallets tracked: {stats.get('unique_wallets','N/A')}",
        f"- Specialist wallets flagged: {stats.get('specialists','N/A')}",
        f"- Last snapshot time: {stats.get('last_snapshot','N/A')}",
        f"- Agent 1 errors (last log): {err_count}",
        "",
    ]
    
    # Try to get some web insights
    queries = [
        "Polymarket prediction markets news",
        "Polymarket trending markets",
        "Polymarket whale activity"
    ]
    all_results = []
    for q in queries:
        results = web_search(q, 3)
        for r in results:
            r['query'] = q
            all_results.append(r)
    
    # Dedup by url
    seen = set()
    unique = []
    for r in all_results:
        url = r.get('url')
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    
    if unique:
        lines.append("## 🌐 Web Insights (last 24h)")
        for i, r in enumerate(unique[:5], 1):
            title = r.get('title','No title')
            url = r.get('url','')
            snippet = r.get('snippet','')
            lines.append(f"{i}. **{title}**")
            if url:
                lines.append(f"   🔗 {url}")
            if snippet:
                lines.append(f"   > {snippet[:200]}...")
            lines.append("")
    else:
        lines.append("## 🌐 Web Insights")
        lines.append("*No web results collected (offline or search failed)*")
        lines.append("")
    
    lines.extend([
        "## 📝 Manual Notes",
        "- Market sentiment: ...",
        "- Whale highlights: ...",
        "- Upcoming events: ...",
        "- Strategy adjustment: ...",
        "",
        "---",
        "*Automated report*"
    ])
    
    with open(out_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ Daily research report saved: {out_path}")
    return out_path

if __name__ == '__main__':
    generate_report()
