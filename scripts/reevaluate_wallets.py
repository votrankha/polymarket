#!/usr/bin/env python3
"""
Re-evaluate all tracked wallets against current filter_rules.py
and generate a clean Active Wallets list for wallet.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agent1_whale_hunter.filter_rules import evaluate

DB_PATH = ROOT / "shared" / "db" / "tracked_wallets.json"
WALLET_MD = ROOT / "agent2_copy_trader" / "wallet.md"

print(f"Reading tracked wallets from {DB_PATH}...")
with open(DB_PATH) as f:
    wallets = json.load(f)

print(f"Total unique addresses in DB: {len(wallets)}")

passed = []
failed = {}

for addr, stats in wallets.items():
    # Normalize field names to match filter_rules expected keys
    normalized = {
        'win_rate': stats.get('win_rate', 0),
        'total_closed': stats.get('total_closed', 0),
        'account_age_days': stats.get('account_age_days', 0),
        'trades_per_month': stats.get('trades_per_month', 0),
        'markets_count': stats.get('markets_count', 0) or stats.get('market_count', 0),
        'bot_flag': stats.get('bot_flag', 0),
        'round_size_ratio': stats.get('round_size_ratio', 0),
        'interval_cv': stats.get('interval_cv', 0),
        'avg_size': stats.get('avg_size', 0),
        'kelly': stats.get('kelly', 0),
        'total_volume': stats.get('total_volume', 0),
    }
    passed_flag, reason = evaluate(normalized)
    if passed_flag:
        passed.append((addr, normalized, reason))
    else:
        failed[addr] = reason

print(f"\nPassed: {len(passed)} | Failed: {len(failed)}")

# Show top failure reasons
from collections import Counter
fail_counts = Counter(failed.values())
print("\nTop discard reasons:")
for reason, cnt in fail_counts.most_common(10):
    print(f"  {reason}: {cnt}")

# Build wallet.md Active Wallets section
lines = []
for addr, stats, reason in passed:
    # Determine budget: specialist $200, normal $50
    specialist = stats.get('specialist', 0) or (reason == "SPECIALIST")
    budget = 200 if specialist else 50
    category = "all"

    # Note: include score and key metrics
    note = f"score={stats['win_rate']:.1f}% wr, kelly={stats['kelly']:.3f}"
    if specialist:
        note = "SPECIALIST " + note

    lines.append(f"{addr.lower()} | {budget} | {category} | {note}")

# Sort by score descending (win_rate as proxy)
lines.sort(key=lambda x: float(x.split('|')[3].split('wr=')[1].split('%')[0]) if 'wr=' in x else 0, reverse=True)

# Read existing wallet.md to preserve header and other sections
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

# Backup old wallet.md
if WALLET_MD.exists():
    backup = WALLET_MD.with_suffix(".md.bak")
    WALLET_MD.rename(backup)
    print(f"Backed up old wallet.md → {backup}")

WALLET_MD.write_text(new_md, encoding="utf-8")
print(f"\n✅ Updated wallet.md with {len(lines)} active wallets")

# Summary stats
specialists = sum(1 for l in lines if "SPECIALIST" in l)
print(f"Specialists: {specialists} | Regular: {len(lines)-specialists}")
