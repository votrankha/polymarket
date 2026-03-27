"""
result_tracker.py — Cập nhật kết quả copy trades
══════════════════════════════════════════════════

Chạy mỗi giờ (tự động từ Agent 1 report_loop, hoặc cron độc lập).

Nhiệm vụ:
  1. Lấy tất cả copy_trades có status='open' từ DB
  2. Gọi /closed-positions của proxy wallet → biết market nào đã resolve
  3. Đối chiếu với open trades → cập nhật status + pnl_usdc

Tại sao cần file riêng?
  Agent 2 không biết khi nào market resolve (không có webhook).
  Cần một job chạy độc lập để poll và cập nhật kết quả.

Dùng:
  python result_tracker.py           # chạy 1 lần rồi thoát
  python result_tracker.py --watch   # chạy mỗi giờ liên tục
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "shared" / ".env", override=True)

from shared.db_store import get_db
from shared.polymarket_client import PolymarketClient

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("result_tracker")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")


async def update_results():
    """
    Lấy closed positions của proxy wallet → cập nhật copy_trades trong DB.

    Logic:
      - open_trades: copy_trades có status='open'
      - closed_positions: tất cả positions đã resolve của proxy wallet
      - Match theo market_id (condition_id)
      - Tính PnL: realizedPnl từ Polymarket
    """
    if not WALLET_ADDRESS:
        logger.error("WALLET_ADDRESS chưa được set trong .env")
        return

    db = get_db()
    client = PolymarketClient()

    try:
        # Lấy open trades cần update
        open_trades = db.get_open_copy_trades()
        if not open_trades:
            logger.info("[tracker] No open trades to update")
            return

        logger.info(f"[tracker] Checking {len(open_trades)} open trades...")

        # Tạo map market_id → trade để tra cứu nhanh
        market_to_trade = {t["market_id"]: t for t in open_trades if t.get("market_id")}

        # Fetch closed positions của proxy wallet
        closed_positions = await client.get_closed_positions(WALLET_ADDRESS, limit=500)
        if not closed_positions:
            logger.info("[tracker] No closed positions found")
            return

        logger.info(f"[tracker] Found {len(closed_positions)} closed positions")

        updated = 0
        for pos in closed_positions:
            cid = pos.get("conditionId", "")
            if cid not in market_to_trade:
                continue

            trade = market_to_trade[cid]
            pnl = float(pos.get("realizedPnl", 0) or 0)

            # Xác định thắng/thua dựa trên PnL
            if pnl > 0:
                status = "won"
                exit_price = 1.0
            elif pnl < 0:
                status = "lost"
                exit_price = 0.0
            else:
                status = "expired"
                exit_price = 0.0

            ok = db.close_copy_trade(
                task_id=trade["task_id"],
                status=status,
                exit_price=exit_price,
                pnl_usdc=pnl,
            )
            if ok:
                updated += 1
                logger.info(
                    f"[tracker] {status.upper():8s} {trade['question'][:50]}"
                    f"  pnl={pnl:+.2f} USDC"
                )

        # Log summary
        summary = db.get_copy_trade_summary()
        logger.info(
            f"[tracker] Updated {updated} trades. "
            f"Total: {summary.get('total',0)} | "
            f"Won: {summary.get('won',0)} | "
            f"Lost: {summary.get('lost',0)} | "
            f"Open: {summary.get('open',0)} | "
            f"PnL: {summary.get('total_pnl',0):+.2f} USDC | "
            f"WR: {summary.get('win_rate_pct',0):.1f}%"
        )

    except Exception as e:
        logger.error(f"[tracker] Error: {e}")
    finally:
        await client.close()


async def watch_loop(interval_hours: float = 1.0):
    """Chạy update_results() mỗi interval_hours giờ."""
    logger.info(f"[tracker] Watch mode — updating every {interval_hours}h")
    while True:
        await update_results()
        logger.info(f"[tracker] Next update in {interval_hours:.1f}h")
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Result Tracker — cập nhật kết quả copy trades")
    p.add_argument("--watch", action="store_true", help="Chạy liên tục mỗi giờ")
    p.add_argument("--interval", type=float, default=1.0, help="Giờ giữa 2 lần update")
    args = p.parse_args()

    try:
        if args.watch:
            asyncio.run(watch_loop(args.interval))
        else:
            asyncio.run(update_results())
    except KeyboardInterrupt:
        logger.info("[tracker] Stopped")
