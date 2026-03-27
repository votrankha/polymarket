#!/usr/bin/env python3
"""
HEALTH CHECK — Polymarket Bot System
Run this before considering live deployment.
"""

import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path("/root/polymarket")
DB = ROOT / "shared" / "db" / "polybot.db"
AGENT1_LOG = ROOT / "shared" / "agent1.log"
AGENT2_WALLET = ROOT / "agent2_copy_trader" / "wallet.md"
SHARED_ENV = ROOT / "shared" / ".env"

def check_file(path, desc):
    if path.exists():
        size = path.stat().st_size
        return f"✅ {desc}: exists ({size:,} bytes)"
    else:
        return f"❌ {desc}: missing"

def check_agent_running(pid_file=None, process_name=None):
    try:
        result = subprocess.run(
            ["pgrep", "-f", "agent1_whale_hunter.py"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            return f"✅ Agent 1 running: PIDs {', '.join(pids)}"
        else:
            return "⚠️ Agent 1: not running (expected if stopped for maintenance)"
    except:
        return "❌ Agent 1: check failed"

def check_db_integrity():
    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        expected = ['whale_trades', 'wallet_snapshots', 'closed_positions']
        missing = [t for t in expected if t not in tables]
        if missing:
            return f"❌ DB missing tables: {missing}"
        # Count rows
        cur.execute("SELECT COUNT(*) FROM whale_trades")
        trades = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_snapshots")
        snapshots = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM closed_positions")
        closed = cur.fetchone()[0]
        conn.close()
        return f"✅ DB: {trades:,} trades, {snapshots:,} snapshots, {closed:,} closed positions"
    except Exception as e:
        return f"❌ DB error: {e}"

def check_agent2_config():
    try:
        with open(AGENT2_WALLET) as f:
            content = f.read()
        has_auto_off = 'AUTO_COPY=off' in content
        has_manual_specialists = 'specialist' in content.lower()
        if has_auto_off and has_manual_specialists:
            return "✅ Agent 2 config: AUTO_COPY=off, specialists present"
        else:
            return "⚠️ Agent 2 config: check settings"
    except:
        return "❌ Agent 2 config: missing"

def check_env_credentials():
    if not SHARED_ENV.exists():
        return "⚠️ .env missing (placeholder only)"
    with open(SHARED_ENV) as f:
        content = f.read()
    has_wallet = 'WALLET_ADDRESS=' in content and not content.split('WALLET_ADDRESS=')[1].startswith('0xYour')
    has_key = 'PRIVATE_KEY=' in content and not content.split('PRIVATE_KEY=')[1].startswith('your_')
    if has_wallet and has_key:
        return "✅ .env credentials: configured"
    else:
        return "⚠️ .env credentials: still placeholder"

def check_recent_logs(lines=50):
    try:
        with open(AGENT1_LOG) as f:
            log_lines = f.readlines()[-lines:]
        errors = sum(1 for l in log_lines if 'ERROR' in l or 'Traceback' in l)
        discards = sum(1 for l in log_lines if 'DISCARD' in l)
        promotes = sum(1 for l in log_lines if 'Promoted to DB' in l)
        if errors == 0:
            return f"✅ Agent 1 logs: no errors, {discards} discards, {promotes} promotes"
        else:
            return f"❌ Agent 1 logs: {errors} errors found"
    except:
        return "❌ Agent 1 logs: unreadable"

def run_all_checks():
    print("="*60)
    print("HEALTH CHECK — Polymarket Bot")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')} Berlin")
    print("="*60)
    print()
    
    checks = [
        ("Files", [
            check_file(DB, "Database"),
            check_file(AGENT2_WALLET, "Agent 2 wallet.md"),
            check_file(SHARED_ENV, "Shared .env"),
        ]),
        ("Processes", [
            check_agent_running(),
        ]),
        ("Database", [
            check_db_integrity(),
        ]),
        ("Agent 2 Config", [
            check_agent2_config(),
        ]),
        ("Credentials", [
            check_env_credentials(),
        ]),
        ("Logs", [
            check_recent_logs(),
        ]),
    ]
    
    for category, items in checks:
        print(f"## {category}")
        for item in items:
            print(item)
        print()
    
    print("="*60)
    print("Recommendation:")
    print(" - If all green: ready for live deployment")
    print(" - If warnings: review config before deploying")
    print(" - If errors: fix before proceeding")
    print("="*60)

if __name__ == '__main__':
    run_all_checks()
