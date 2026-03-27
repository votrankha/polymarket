#!/usr/bin/env python3
"""
Refresh wallet history & recalc metrics for selected wallets.
Smart logic: skip if already have full history, otherwise fetch full.

Usage:
  python refresh_wallet_history.py --address 0x... [--address 0x...] [--all-specialists]
  python refresh_wallet_history.py --top-active 20
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project paths
sys.path.append('/root/polymarket/shared')
sys.path.append('/root/polymarket/agent1_whale_hunter')

from polymarket_client import PolymarketClient

# Configuration
DB_PATH = '/root/polymarket/shared/db/polybot.db'
WALLET_MD_PATH = '/root/polymarket/agent2_copy_trader/wallet.md'
CONCURRENT_LIMIT = 4  # số concurrent requests

class WalletRefresher:
    def __init__(self):
        self.client = PolymarketClient()
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._ensure_metadata_table()
    
    def _ensure_metadata_table(self):
        """Create wallet_metadata table if not exists."""
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_metadata (
                address TEXT PRIMARY KEY,
                last_full_fetch_ts INTEGER DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                needs_refresh INTEGER DEFAULT 1,
                last_updated INTEGER DEFAULT 0
            )
        """)
        self.db.commit()
    
    def get_metadata(self, address: str) -> Optional[dict]:
        """Get metadata for a wallet."""
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM wallet_metadata WHERE address = ?",
            (address.lower(),)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    
    def set_metadata(self, address: str, trade_count: int, needs_refresh: int = 0):
        """Update metadata for a wallet."""
        now = int(datetime.now(timezone.utc).timestamp())
        cur = self.db.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO wallet_metadata 
            (address, last_full_fetch_ts, trade_count, needs_refresh, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (address.lower(), now if needs_refresh == 0 else 0, trade_count, needs_refresh, now))
        self.db.commit()
    
    def needs_full_refresh(self, address: str) -> bool:
        """
        Determine if wallet needs full history fetch.
        
        Returns True if:
        - No metadata exists (new wallet)
        - trade_count < 50 (not enough data)
        - last_full_fetch_ts > 30 days ago
        - needs_refresh flag set to 1
        """
        meta = self.get_metadata(address)
        now = int(datetime.now(timezone.utc).timestamp())
        
        if not meta:
            return True
        
        # Check explicit refresh flag
        if meta.get('needs_refresh', 0) == 1:
            return True
        
        # Check trade count
        if meta.get('trade_count', 0) < 50:
            return True
        
        # Check age of last full fetch
        last_fetch = meta.get('last_full_fetch_ts', 0)
        if now - last_fetch > 30 * 86400:  # 30 days
            return True
        
        return False
    
    async def fetch_all_history(self, address: str):
        """Fetch ALL closed positions and trades for a wallet."""
        print(f"  📥 Fetching FULL history for {address[:10]}...")
        
        try:
            # 1. Get ALL closed positions
            closed = await self.client.get_closed_positions(address, limit=999999)
            print(f"    Closed positions: {len(closed)}")
            
            # 2. Get ALL wallet activity (trades)
            trades = await self.client.get_wallet_activity(address, limit=999999)
            print(f"    Raw trades: {len(trades)}")
            
            return closed, trades
        except Exception as e:
            print(f"    ❌ Error fetching: {e}")
            return [], []
    
    async def fetch_incremental_closed(self, address: str) -> list:
        """Fetch only recent closed positions (for ongoing tracking)."""
        print(f"  📥 Fetching incremental closed positions for {address[:10]}...")
        
        try:
            # Get last known closed position timestamp from DB
            cur = self.db.cursor()
            cur.execute("""
                SELECT MAX(ts) FROM wallet_snapshots WHERE address = ?
            """, (address.lower(),))
            row = cur.fetchone()
            last_ts = row[0] if row and row[0] else 0
            
            # Fetch closed positions (full but we'll filter later)
            closed = await self.client.get_closed_positions(address, limit=2000)
            
            # Filter only new ones (after last_ts)
            if last_ts > 0:
                new_closed = [c for c in closed if int(c.get('resolved_at', c.get('timestamp', 0)) or 0) > last_ts]
                print(f"    Closed positions: {len(closed)} total, {len(new_closed)} new")
                return new_closed
            else:
                print(f"    Closed positions: {len(closed)} (no previous data)")
                return closed
        except Exception as e:
            print(f"    ❌ Error fetching: {e}")
            return []
    
    def calculate_metrics(self, closed: list, trades: list) -> dict:
        """Calculate wallet metrics from raw data."""
        if not closed:
            return {}
        
        total_positions = len(closed)
        wins = sum(1 for p in closed if float(p.get('realizedPnl', 0)) > 0)
        losses = sum(1 for p in closed if float(p.get('realizedPnl', 0)) < 0)
        total_pnl = sum(float(p.get('realizedPnl', 0)) for p in closed)
        
        win_rate = (wins / total_positions * 100) if total_positions > 0 else 0
        
        # Average trade size (from closed positions invested)
        avg_size = sum(float(p.get('invested', 0)) for p in closed) / total_positions if total_positions else 0
        
        # Total volume
        total_volume = sum(float(p.get('invested', 0)) for p in closed)
        
        # Account age: earliest trade timestamp
        if trades:
            timestamps = []
            for t in trades:
                ts = t.get('timestamp') or t.get('createdAt')
                if ts:
                    timestamps.append(int(ts))
            if timestamps:
                earliest_ts = min(timestamps)
                account_age_days = (datetime.now(timezone.utc).timestamp() - earliest_ts) / 86400
            else:
                account_age_days = 0
        else:
            account_age_days = 0
        
        # Trades per month
        trades_per_month = len(trades) / (account_age_days / 30) if account_age_days > 0 else 0
        
        # Kelly criterion (simplified version)
        wins_pnl = [float(p.get('realizedPnl', 0)) for p in closed if float(p.get('realizedPnl', 0)) > 0]
        losses_pnl = [abs(float(p.get('realizedPnl', 0))) for p in closed if float(p.get('realizedPnl', 0)) < 0]
        
        avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        avg_loss = sum(losses_pnl) / len(losses_pnl) if losses_pnl else 0
        
        win_prob = wins / total_positions if total_positions > 0 else 0
        loss_prob = losses / total_positions if total_positions > 0 else 0
        
        # Kelly formula: f* = (p * b - q) / b
        # where p = win prob, q = loss prob, b = win/loss ratio
        if avg_loss > 0 and avg_win > 0:
            b = avg_win / avg_loss
            kelly = (win_prob * b - loss_prob) / b
            kelly = max(0, min(1, kelly))  # clamp 0-1
        else:
            kelly = 0
        
        # Score calculation (simplified, matching Agent1)
        # Normalize metrics to 0-1 range
        wr_norm = win_rate / 100.0
        kelly_norm = kelly  # already 0-1
        volume_norm = min(1.0, total_volume / 1000000)  # cap at $1M
        freq_norm = min(1.0, trades_per_month / 100)  # cap at 100 trades/month
        age_norm = min(1.0, account_age_days / 180)  # cap at 180 days
        
        score = (
            wr_norm * 0.25 +
            kelly_norm * 0.25 +
            volume_norm * 0.20 +
            freq_norm * 0.15 +
            age_norm * 0.15
        )
        
        # Check if specialist (from manual wallets)
        specialist = self.is_specialist(address)
        if specialist:
            score *= 1.2  # 20% bonus
            score = min(1.0, score)  # cap at 1.0
        
        return {
            'win_rate': win_rate,
            'kelly': kelly,
            'total_pnl': total_pnl,
            'avg_size': avg_size,
            'total_volume': total_volume,
            'account_age_days': account_age_days,
            'trades_per_month': trades_per_month,
            'total_positions': total_positions,
            'total_trades_raw': len(trades),
            'score': score,
            'specialist': 1 if specialist else 0,
            'updated_at': int(datetime.now(timezone.utc).timestamp()),
        }
    
    def is_specialist(self, address: str) -> bool:
        """Check if wallet is in Manual Wallets (specialist)."""
        try:
            with open(WALLET_MD_PATH, 'r') as f:
                content = f.read()
                # Look for address in Manual Wallets section with SPECIALIST tag
                address_lower = address.lower()
                if address_lower in content.lower() and 'SPECIALIST' in content:
                    # Double check it's in manual section
                    in_manual = False
                    for line in content.split('\n'):
                        if line.strip().startswith('## Manual Wallets'):
                            in_manual = True
                        elif line.strip().startswith('## ') and in_manual:
                            in_manual = False
                        if in_manual and address_lower in line.lower():
                            return True
        except:
            pass
        return False
    
    def get_budget_category(self, address: str) -> tuple:
        """Get budget and category from wallet.md for this address."""
        try:
            with open(WALLET_MD_PATH, 'r') as f:
                for line in f:
                    if line.strip().startswith('0x') and '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                        if parts[0].lower() == address.lower():
                            budget = int(parts[1]) if parts[1].isdigit() else 50
                            category = parts[2] if len(parts) > 2 else 'all'
                            return budget, category
        except:
            pass
        return 50, 'all'  # defaults
    
    def save_metrics(self, address: str, metrics: dict):
        """Update wallet_snapshots table with new metrics."""
        if not metrics:
            return False
        
        cur = self.db.cursor()
        
        # Check if exists latest snapshot at this timestamp
        cur.execute("""
            SELECT id FROM wallet_snapshots 
            WHERE address = ? AND ts = ?
        """, (address.lower(), metrics['updated_at']))
        
        if cur.fetchone():
            print(f"    ⚠️  Snapshot already exists for this timestamp, skipping")
            return False
        
        cur.execute("""
            INSERT INTO wallet_snapshots 
            (address, ts, score, win_rate, kelly, net_pnl, avg_size, total_closed, 
             trades_per_month, account_age_days, total_volume, bot_flag, source, specialist, primary_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            address.lower(),
            metrics['updated_at'],
            metrics.get('score', 0),
            metrics['win_rate'],
            metrics['kelly'],
            metrics['total_pnl'],
            metrics['avg_size'],
            metrics['total_positions'],
            metrics['trades_per_month'],
            metrics['account_age_days'],
            metrics['total_volume'],
            0,  # bot_flag (TODO)
            'refresh',
            metrics.get('specialist', 0),
            'polymarket'  # primary_category
        ))
        self.db.commit()
        print(f"    ✅ Metrics saved: win_rate={metrics['win_rate']:.1f}%, kelly={metrics['kelly']:.3f}, score={metrics.get('score',0):.3f}")
        return True
    
    def update_wallet_md(self, address: str, metrics: dict, budget: int, category: str):
        """Update wallet.md Active Wallets entry with new metrics."""
        with open(WALLET_MD_PATH, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        found = False
        in_active_section = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Track section
            if stripped.startswith('## Active Wallets'):
                in_active_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith('## ') and in_active_section:
                in_active_section = False
            
            # Update wallet entry in Active Wallets
            if in_active_section and stripped.startswith('0x') and '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if parts[0].lower() == address.lower():
                    # Build new entry with updated metrics
                    note = f"score={metrics.get('score',0):.2f} kelly={metrics['kelly']:.3f} wr={metrics['win_rate']:.1f}%"
                    new_line = f"{address} | {budget} | {category} | {note}\n"
                    new_lines.append(new_line)
                    found = True
                    print(f"    ✅ Updated wallet.md: budget=${budget}, category={category}")
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        if not found:
            print(f"    ⚠️  Address not in Active Wallets section - manual update needed")
        
        # Write back
        with open(WALLET_MD_PATH, 'w') as f:
            f.writelines(new_lines)
    
    def save_trades_to_db(self, address: str, trades: list):
        """Save raw trades to whale_trades table (ignore duplicates)."""
        if not trades:
            return 0
        
        cur = self.db.cursor()
        saved = 0
        
        for t in trades:
            try:
                shares = float(t.get('size', 0) or 0)
                price = float(t.get('price', 0) or 0)
                usdc = shares * price
                
                # Generate tx_hash if missing
                tx_hash = t.get('transactionHash', t.get('txHash'))
                if not tx_hash:
                    ts = int(t.get('timestamp', t.get('createdAt', 0)) or 0)
                    tx_hash = f"{address.lower()}_{ts}_{price:.2f}"
                
                cur.execute("""
                    INSERT OR IGNORE INTO whale_trades 
                    (tx_hash, address, market_id, question, outcome, price, usdc_size, shares, side, ts, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tx_hash,
                    address.lower(),
                    t.get('conditionId', ''),
                    t.get('title', '')[:200],
                    'YES' if str(t.get('outcomeIndex', t.get('outcome',''))) in ('0','yes','YES') else 'NO',
                    str(price),
                    str(usdc),
                    shares,
                    t.get('side', 'BUY'),
                    int(t.get('timestamp', t.get('createdAt', 0)) or 0),
                    'refresh'
                ))
                saved += 1
            except Exception as e:
                continue
        
        self.db.commit()
        print(f"    ✅ Saved {saved} trades to whale_trades DB")
        return saved
    
    async def refresh_wallet(self, address: str):
        """Full refresh workflow for one wallet."""
        address = address.lower()
        print(f"\n{'='*80}")
        print(f"🔄 Refreshing: {address}")
        print(f"{'='*80}")
        
        # Check if needs full refresh
        needs_full = self.needs_full_refresh(address)
        meta = self.get_metadata(address)
        print(f"   Metadata: trade_count={meta.get('trade_count',0) if meta else 0}, last_fetch={meta.get('last_full_fetch_ts',0) if meta else 'never'}")
        print(f"   → Needs full refresh: {needs_full}")
        
        if needs_full:
            # Fetch full history
            closed, trades = await self.fetch_all_history(address)
            
            if not closed:
                print("   ⚠️  No closed positions - wallet may be inactive")
                self.set_metadata(address, trade_count=len(trades), needs_refresh=1)
                return
            
            # Calculate metrics
            metrics = self.calculate_metrics(closed, trades)
            
            # Save metrics to wallet_snapshots
            self.save_metrics(address, metrics)
            
            # Save trades
            self.save_trades_to_db(address, trades)
            
            # Update wallet.md
            budget, category = self.get_budget_category(address)
            self.update_wallet_md(address, metrics, budget, category)
            
            # Update metadata
            self.set_metadata(address, trade_count=len(trades), needs_refresh=0)
            
        else:
            # Incremental: only fetch new closed positions
            new_closed = await self.fetch_incremental_closed(address)
            
            if not new_closed:
                print("   ✅ No new closed positions")
                return
            
            # For incremental, we don't recalc full metrics (would be skewed)
            # Instead, just save the new closed positions
            cur = self.db.cursor()
            for pos in new_closed:
                # Insert closed position if not exists
                cur.execute("""
                    INSERT OR IGNORE INTO closed_positions 
                    (address, market_id, question, outcome, realized_pnl, invested, shares, avg_price, end_price, result, resolved_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    address,
                    pos.get('conditionId', ''),
                    pos.get('title', '')[:200],
                    pos.get('outcome', ''),
                    float(pos.get('realizedPnl', 0)),
                    float(pos.get('invested', 0)),
                    float(pos.get('shares', 0)),
                    float(pos.get('avgPrice', 0)),
                    float(pos.get('endPrice', 0)),
                    'won' if float(pos.get('realizedPnl', 0)) > 0 else 'lost',
                    int(pos.get('resolvedAt', 0)),
                    int(datetime.now(timezone.utc).timestamp())
                ))
            self.db.commit()
            print(f"    ✅ Saved {len(new_closed)} new closed positions")
            
            # Update metadata timestamp
            meta = self.get_metadata(address) or {}
            self.set_metadata(address, trade_count=meta.get('trade_count', 0), needs_refresh=0)
        
        print(f"   ✅ Refresh complete")
    
    async def run(self, addresses: list):
        """Run refresh for multiple addresses with concurrency."""
        sem = asyncio.Semaphore(CONCURRENT_LIMIT)
        
        async def bounded_refresh(addr):
            async with sem:
                try:
                    await self.refresh_wallet(addr)
                except Exception as e:
                    print(f"   ❌ Error: {e}")
        
        tasks = [bounded_refresh(addr) for addr in addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for exceptions
        for addr, result in zip(addresses, results):
            if isinstance(result, Exception):
                print(f"❌ Wallet {addr[:10]} failed: {result}")
        
        self.db.close()
        print(f"\n✅ All done! Refreshed {len(addresses)} wallets.")

def get_all_specialists() -> list:
    """Extract all specialist wallet addresses from wallet.md."""
    specialists = []
    try:
        with open(WALLET_MD_PATH, 'r') as f:
            lines = f.readlines()
        
        in_manual = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('## Manual Wallets'):
                in_manual = True
            elif stripped.startswith('## ') and in_manual:
                in_manual = False
            elif in_manual and stripped.startswith('0x') and '|' in stripped:
                parts = [p.strip() for p in stripped.split('|')]
                if len(parts) >= 2:
                    specialists.append(parts[0])
    except Exception as e:
        print(f"Error reading wallet.md: {e}")
    
    return specialists

def get_top_active_wallets(n: int) -> list:
    """Get top N wallets from Active Wallets section by score."""
    try:
        with open(WALLET_MD_PATH, 'r') as f:
            lines = f.readlines()
        
        wallets = []
        in_active = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('## Active Wallets'):
                in_active = True
                continue
            elif stripped.startswith('## ') and in_active:
                break
            
            if in_active and stripped.startswith('0x') and '|' in stripped:
                parts = [p.strip() for p in stripped.split('|')]
                if len(parts) >= 4:
                    address = parts[0]
                    # Parse score from note (last part)
                    note = parts[3]
                    score = 0.0
                    try:
                        # Extract score=0.xx
                        import re
                        match = re.search(r'score=([\d.]+)', note)
                        if match:
                            score = float(match.group(1))
                    except:
                        pass
                    wallets.append((address, score))
        
        # Sort by score descending
        wallets.sort(key=lambda x: x[1], reverse=True)
        return [addr for addr, score in wallets[:n]]
    except Exception as e:
        print(f"Error reading wallet.md: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description='Refresh wallet history & recalc metrics (smart incremental)')
    parser.add_argument('--address', action='append', help='Wallet address to refresh')
    parser.add_argument('--all-specialists', action='store_true', help='Refresh all specialist wallets')
    parser.add_argument('--top-active', type=int, help='Refresh top N active wallets by score')
    parser.add_argument('--force', action='store_true', help='Force full refresh even if already up-to-date')
    args = parser.parse_args()
    
    if not args.address and not args.all_specialists and not args.top_active:
        parser.error('Must specify --address, --all-specialists, or --top-active')
    
    refresher = WalletRefresher()
    addresses = []
    
    if args.address:
        addresses.extend(args.address)
    
    if args.all_specialists:
        specialists = get_all_specialists()
        print(f"Found {len(specialists)} specialists in wallet.md")
        addresses.extend(specialists)
    
    if args.top_active:
        top_wallets = get_top_active_wallets(args.top_active)
        print(f"Selected top {args.top_active} active wallets")
        addresses.extend(top_wallets)
    
    # Remove duplicates
    addresses = list(set([addr.lower() for addr in addresses]))
    
    print(f"🚀 Refreshing {len(addresses)} wallets...")
    print(f"   Concurrency: {CONCURRENT_LIMIT}")
    
    # If --force, mark all as needing full refresh
    if args.force:
        for addr in addresses:
            refresher.set_metadata(addr.lower(), trade_count=0, needs_refresh=1)
        print("   ⚠️  Force refresh enabled - will fetch full history for all")
    
    asyncio.run(refresher.run(addresses))

if __name__ == '__main__':
    main()
