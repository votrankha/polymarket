#!/usr/bin/env python3
"""
FIX CLOSED_POSITIONS DATA INCONSISTENCY
---------------------------------------
Vấn đề: realized_pnl được lưu dương cho cả 'lost' và 'won', dẫn đến win_rate sai.
Logic đúng: realized_pnl > 0 → 'won', realized_pnl < 0 → 'lost'

Hành động:
1. Backup DB
2. Sửa result='lost' thành 'won' nếu realized_pnl > 0
3. Sửa result='won' thành 'lost' nếu realized_pnl < 0
4. Log thống kê số record đã sửa
"""

import sqlite3
from datetime import datetime
import shutil
from pathlib import Path

DB_PATH = Path("/root/polymarket/shared/db/polybot.db")
BACKUP_DIR = Path("/root/polymarket/shared/db/backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def backup_db():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"polybot_backup_{ts}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ Backed up DB to: {backup_path}")
    return backup_path

def analyze_inconsistency():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n📊 ANALYZING DATA INCONSISTENCY...")

    # Tổng số closed positions
    cur.execute("SELECT COUNT(*) FROM closed_positions")
    total = cur.fetchone()[0]
    print(f"Total closed_positions: {total}")

    # Phân theo result
    cur.execute("SELECT result, COUNT(*) FROM closed_positions GROUP BY result")
    print("\nBy result:")
    for result, count in cur.fetchall():
        print(f"  {result}: {count}")

    # realized_pnl dương nhưng result='lost'
    cur.execute("""
        SELECT COUNT(*) FROM closed_positions
        WHERE result = 'lost' AND realized_pnl > 0
    """)
    lost_pos_pnl = cur.fetchone()[0]
    print(f"\n⚠️  Lost with positive pnl: {lost_pos_pnl}")

    # realized_pnl âm nhưng result='won'
    cur.execute("""
        SELECT COUNT(*) FROM closed_positions
        WHERE result = 'won' AND realized_pnl < 0
    """)
    won_neg_pnl = cur.fetchone()[0]
    print(f"⚠️  Won with negative pnl: {won_neg_pnl}")

    # realized_pnl = 0 với cả lost và won
    cur.execute("SELECT COUNT(*) FROM closed_positions WHERE realized_pnl = 0")
    zero_pnl = cur.fetchone()[0]
    print(f"Zero pnl (ignore): {zero_pnl}")

    conn.close()
    return lost_pos_pnl, won_neg_pnl

def fix_inconsistency():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n🔧 FIXING DATA...")

    # Fix: lost + positive pnl → won
    cur.execute("""
        UPDATE closed_positions
        SET result = 'won'
        WHERE result = 'lost' AND realized_pnl > 0
    """)
    fix1 = cur.rowcount
    print(f"✅ Fixed lost+positive → won: {fix1} rows")

    # Fix: won + negative pnl → lost
    cur.execute("""
        UPDATE closed_positions
        SET result = 'lost'
        WHERE result = 'won' AND realized_pnl < 0
    """)
    fix2 = cur.rowcount
    print(f"✅ Fixed won+negative → lost: {fix2} rows")

    conn.commit()
    conn.close()
    return fix1, fix2

def verify_fix():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n✅ VERIFYING AFTER FIX...")

    cur.execute("SELECT result, COUNT(*) FROM closed_positions GROUP BY result")
    print("\nBy result (after fix):")
    for result, count in cur.fetchall():
        print(f"  {result}: {count}")

    cur.execute("""
        SELECT COUNT(*) FROM closed_positions
        WHERE (result = 'lost' AND realized_pnl > 0)
           OR (result = 'won' AND realized_pnl < 0)
    """)
    remaining = cur.fetchone()[0]
    print(f"\nRemaining inconsistencies: {remaining}")

    conn.close()
    return remaining

def main():
    print("🔧 FIXING closed_positions DATA INCONSISTENCY")
    print("=" * 50)

    # Backup first
    backup_path = backup_db()

    # Analyze
    lost_pos, won_neg = analyze_inconsistency()

    if lost_pos == 0 and won_neg == 0:
        print("\n🎉 No inconsistencies found! Data is clean.")
        return

    # Confirm if not auto
    total_fix = lost_pos + won_neg
    if total_fix > 0:
        print(f"\n⚠️  Total inconsistent rows: {total_fix}")
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == '--auto':
            print("Auto-confirmed with --auto")
            response = 'yes'
        else:
            response = input(f"Proceed to fix {total_fix} rows? (yes/no): ").strip().lower()
        if response != 'yes':
            print("❌ Aborted.")
            return
    else:
        print("\n🎉 No inconsistencies found! Data is clean.")
        return

    # Fix
    fix1, fix2 = fix_inconsistency()

    # Verify
    remaining = verify_fix()

    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"  Backed up: {backup_path}")
    print(f"  Fixed lost+positive→won: {fix1}")
    print(f"  Fixed won+negative→lost: {fix2}")
    print(f"  Remaining issues: {remaining}")
    print("=" * 50)

if __name__ == "__main__":
    main()
