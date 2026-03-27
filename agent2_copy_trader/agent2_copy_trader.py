"""
╔══════════════════════════════════════════════════════════════════╗
║  AGENT 2 — Copy Trader                                           ║
║                                                                  ║
║  Hai chế độ copy trade, bật/tắt độc lập:                        ║
║                                                                  ║
║  MODE A — AUTO  (copy ví do Agent 1 cập nhật vào wallet.md)     ║
║    · Đọc queue từ shared/copy_queue.jsonl                        ║
║    · Bật/tắt bằng:  AUTO_COPY=on|off  trong wallet.md           ║
║                                                                  ║
║  MODE B — MANUAL  (copy ví chỉ định tay trong wallet.md)        ║
║    · Tự poll từng ví trong [MANUAL WALLETS]                      ║
║    · Bật/tắt bằng:  MANUAL_COPY=on|off  trong wallet.md         ║
║    · Volume per wallet cấu hình riêng                            ║
║                                                                  ║
║  Hai mode có thể bật đồng thời hoặc tắt hoàn toàn.             ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python agent2_copy_trader.py           # chạy theo config trong wallet.md
    python agent2_copy_trader.py --auto    # bật AUTO mode (override wallet.md)
    python agent2_copy_trader.py --manual  # bật MANUAL mode (override wallet.md)
    python agent2_copy_trader.py --status  # print trạng thái rồi exit
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from colorama import Fore, Style, init
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data as encode_structured_data
from web3 import Web3

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "shared" / ".env")

from shared.polymarket_client import PolymarketClient

# ── Logging ───────────────────────────────────────────────────────────────────
init(autoreset=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "shared" / "agent2.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("agent2")

# ── Paths & env ───────────────────────────────────────────────────────────────
WALLET_MD    = ROOT / "agent2_copy_trader" / "wallet.md"
QUEUE_PATH   = ROOT / "shared" / "copy_queue.jsonl"
CURSOR_PATH  = ROOT / "shared" / ".queue_cursor"

WALLET_ADDR  = os.getenv("WALLET_ADDRESS", "")
PRIVATE_KEY  = os.getenv("PRIVATE_KEY",    "")
POLYGON_RPC  = os.getenv("POLYGON_RPC",    "https://polygon-rpc.com")

# EIP-712 constants
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
USDC_ADDR    = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CHAIN_ID     = 137

EIP712_DOMAIN = {
    "name": "Polymarket CTF Exchange",
    "version": "1",
    "chainId": CHAIN_ID,
    "verifyingContract": CTF_EXCHANGE,
}
ORDER_TYPES = {
    "EIP712Domain": [
        {"name": "name",              "type": "string"},
        {"name": "version",           "type": "string"},
        {"name": "chainId",           "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Order": [
        {"name": "salt",          "type": "uint256"},
        {"name": "maker",         "type": "address"},
        {"name": "signer",        "type": "address"},
        {"name": "taker",         "type": "address"},
        {"name": "tokenId",       "type": "uint256"},
        {"name": "makerAmount",   "type": "uint256"},
        {"name": "takerAmount",   "type": "uint256"},
        {"name": "expiration",    "type": "uint256"},
        {"name": "nonce",         "type": "uint256"},
        {"name": "feeRateBps",    "type": "uint256"},
        {"name": "side",          "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
#  WALLET.MD PARSER
# ══════════════════════════════════════════════════════════════════════════════
class WalletConfig:
    """
    Đọc và parse wallet.md.

    Format wallet.md:
    ─────────────────────────────────────────────────────────
    ## Settings
    AUTO_COPY=on              # on | off
    MANUAL_COPY=on            # on | off
    MAX_TOTAL_BUDGET=500
    MAX_PER_MARKET=100
    STOP_LOSS_PCT=30
    MAX_OPEN_POSITIONS=10
    MIN_SPREAD=0.05
    SCAN_INTERVAL_SECONDS=30
    MAX_COPY_DELAY_SECONDS=10

    ## Active Wallets
    # [Agent1 auto-update] ...
    0xABC...  | 25 | all | score=0.84 kelly=0.21 wr=72%
    0xDEF...  | 50 | all | score=0.91 kelly=0.31 wr=81%

    ## Manual Wallets
    # Ví copy tay — không phụ thuộc Agent 1
    0x111...  | 30 | crypto  | Whale X — tay chỉ định
    0x222...  | 75 | geo     | Whale Y — high conviction

    ## Blacklist
    0xBAD...  | spam bot
    ─────────────────────────────────────────────────────────
    """

    def __init__(self):
        self.auto_copy:    bool       = False
        self.manual_copy:  bool       = False
        self.settings:     Dict       = {}
        self.auto_wallets: List[Dict] = []   # from ## Active Wallets (Agent 1)
        self.manual_wallets: List[Dict] = [] # from ## Manual Wallets (user-defined)
        self.blacklist:    Set[str]   = set()
        self._mtime: float = 0.0

    def load(self) -> "WalletConfig":
        try:
            mtime = WALLET_MD.stat().st_mtime
            if mtime == self._mtime:
                return self   # nothing changed
            self._mtime = mtime
            self._parse(WALLET_MD.read_text(encoding="utf-8"))
            logger.info(
                f"{Fore.CYAN}[wallet.md] Reloaded — "
                f"AUTO={self.auto_copy_str}  "
                f"MANUAL={self.manual_copy_str}  "
                f"auto_wallets={len(self.auto_wallets)}  "
                f"manual_wallets={len(self.manual_wallets)}{Style.RESET_ALL}"
            )
        except Exception as e:
            logger.error(f"[wallet.md] Parse error: {e}")
        return self

    def _parse(self, text: str):
        settings: Dict    = {}
        auto_w: List[Dict]   = []
        manual_w: List[Dict] = []
        blacklist: Set[str]  = set()

        section = None  # "settings" | "active" | "manual" | "blacklist"

        for raw in text.splitlines():
            line = raw.strip()

            # Section headers
            if re.match(r"##\s*settings", line, re.I):
                section = "settings"; continue
            if re.match(r"##\s*active\s*wallets?", line, re.I):
                section = "active";   continue
            if re.match(r"##\s*manual\s*wallets?", line, re.I):
                section = "manual";   continue
            if re.match(r"##\s*blacklist", line, re.I):
                section = "blacklist"; continue
            if line.startswith("##"):
                section = None; continue

            # Skip blanks and pure comments
            if not line or line.startswith("#"):
                continue

            # Settings  KEY=VALUE  (anywhere, any section)
            m = re.match(r"^([A-Z_]+)\s*=\s*(.+)$", line)
            if m:
                settings[m.group(1).strip()] = m.group(2).strip()
                continue

            # Wallet line  ADDRESS | volume | category | note
            if line.startswith("0x"):
                parts = [p.strip() for p in line.split("|")]
                addr  = parts[0].lower()
                try:
                    vol = float(parts[1]) if len(parts) > 1 else 25.0
                except ValueError:
                    vol = 25.0
                cat  = parts[2] if len(parts) > 2 else "all"
                note = parts[3] if len(parts) > 3 else ""
                entry = {"address": addr, "volume_usdc": vol,
                         "category": cat, "note": note}

                if section == "active":
                    auto_w.append(entry)
                elif section == "manual":
                    manual_w.append(entry)
                elif section == "blacklist":
                    blacklist.add(addr)
                continue

            # Blacklist short form  0xADDR | reason
            if section == "blacklist":
                parts = [p.strip() for p in line.split("|")]
                if parts[0].startswith("0x"):
                    blacklist.add(parts[0].lower())

        # Apply
        self.settings      = settings
        self.auto_wallets  = [w for w in auto_w   if w["address"] not in blacklist]
        self.manual_wallets= [w for w in manual_w if w["address"] not in blacklist]
        self.blacklist     = blacklist

        def _flag(key: str, default: bool) -> bool:
            raw = settings.get(key, "on" if default else "off").lower()
            return raw in ("on", "1", "true", "yes")

        self.auto_copy   = _flag("AUTO_COPY",   True)
        self.manual_copy = _flag("MANUAL_COPY", True)

    @property
    def auto_copy_str(self) -> str:
        return f"{Fore.GREEN}ON{Style.RESET_ALL}" if self.auto_copy else f"{Fore.RED}OFF{Style.RESET_ALL}"

    @property
    def manual_copy_str(self) -> str:
        return f"{Fore.GREEN}ON{Style.RESET_ALL}" if self.manual_copy else f"{Fore.RED}OFF{Style.RESET_ALL}"

    def get(self, key: str, default):
        val = self.settings.get(key, os.getenv(key, str(default)))
        try:
            return type(default)(val)
        except Exception:
            return default

    def all_wallets(self) -> List[Dict]:
        """Trả về tất cả ví đang active (auto + manual, không trùng)."""
        seen  = set()
        out   = []
        for w in (*self.manual_wallets, *self.auto_wallets):
            if w["address"] not in seen:
                seen.add(w["address"])
                out.append(w)
        return out


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER SIGNER  (EIP-712 + Polygon RPC)
# ══════════════════════════════════════════════════════════════════════════════
class OrderSigner:
    def __init__(self):
        if not PRIVATE_KEY:
            raise ValueError("PRIVATE_KEY not set in shared/.env")
        self.account = Account.from_key(PRIVATE_KEY)
        self.w3      = Web3(Web3.HTTPProvider(POLYGON_RPC))

    def usdc_balance(self) -> float:
        abi = [{"inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view", "type": "function"}]
        try:
            c   = self.w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDR), abi=abi)
            raw = c.functions.balanceOf(Web3.to_checksum_address(self.account.address)).call()
            return raw / 1e6
        except Exception as e:
            logger.warning(f"[USDC] balance error: {e}")
            return 0.0

    def sign_order(
        self,
        token_id:     str,
        side:         int,   # 0=BUY  1=SELL
        maker_amount: int,
        taker_amount: int,
        expiration:   int,
    ) -> Tuple[dict, str]:
        order = {
            "salt":          int(time.time() * 1000),
            "maker":         self.account.address,
            "signer":        self.account.address,
            "taker":         "0x0000000000000000000000000000000000000000",
            "tokenId":       int(token_id) if str(token_id).isdigit() else 0,
            "makerAmount":   maker_amount,
            "takerAmount":   taker_amount,
            "expiration":    expiration,
            "nonce":         0,
            "feeRateBps":    0,
            "side":          side,
            "signatureType": 0,
        }
        sig = self.account.sign_message(
            encode_structured_data({"types": ORDER_TYPES,
                                    "primaryType": "Order",
                                    "domain": EIP712_DOMAIN,
                                    "message": order})
        ).signature.hex()
        return order, sig


# ══════════════════════════════════════════════════════════════════════════════
#  COPY TRADER AGENT
# ══════════════════════════════════════════════════════════════════════════════
class CopyTraderAgent:

    def __init__(self, force_auto: bool = False, force_manual: bool = False):
        self.client  = PolymarketClient()
        self.signer  = OrderSigner()
        self.cfg     = WalletConfig()

        self._force_auto   = force_auto
        self._force_manual = force_manual

        # State
        self._open_positions: Dict[str, dict] = {}
        self._deployed:       float           = 0.0
        self._seen_tasks:     Set[str]        = set()
        self._last_polled:    Dict[str, int]  = {}

        self._stats = {
            "auto_copied": 0, "manual_copied": 0,
            "wins": 0, "losses": 0, "pnl": 0.0, "skipped": 0,
        }
        self._start_ts = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    #  MAIN RUN
    # ─────────────────────────────────────────────────────────────────────────
    async def run(self):
        self.cfg.load()
        self._print_banner()

        await asyncio.gather(
            self._config_watcher(),
            self._auto_mode_loop(),
            self._manual_mode_loop(),
            self._stop_loss_loop(),
            self._stats_loop(),
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  CONFIG WATCHER  — detect wallet.md changes every 15s
    # ─────────────────────────────────────────────────────────────────────────
    async def _config_watcher(self):
        while True:
            await asyncio.sleep(15)
            try:
                prev_auto   = self.cfg.auto_copy
                prev_manual = self.cfg.manual_copy
                prev_auto_n = len(self.cfg.auto_wallets)
                prev_man_n  = len(self.cfg.manual_wallets)

                self.cfg.load()

                # Log meaningful changes
                if self.cfg.auto_copy != prev_auto:
                    logger.info(
                        f"[CONFIG] AUTO mode: "
                        f"{'ON' if prev_auto else 'OFF'} → {self.cfg.auto_copy_str}"
                    )
                if self.cfg.manual_copy != prev_manual:
                    logger.info(
                        f"[CONFIG] MANUAL mode: "
                        f"{'ON' if prev_manual else 'OFF'} → {self.cfg.manual_copy_str}"
                    )
                if len(self.cfg.auto_wallets) != prev_auto_n:
                    logger.info(
                        f"[CONFIG] Auto wallet list: {prev_auto_n} → {len(self.cfg.auto_wallets)}"
                    )
                if len(self.cfg.manual_wallets) != prev_man_n:
                    logger.info(
                        f"[CONFIG] Manual wallet list: {prev_man_n} → {len(self.cfg.manual_wallets)}"
                    )
            except Exception as e:
                logger.debug(f"[CONFIG] watcher error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  MODE A — AUTO COPY  (reads copy_queue.jsonl from Agent 1)
    # ─────────────────────────────────────────────────────────────────────────
    async def _auto_mode_loop(self):
        logger.info(f"[AUTO] Loop started")
        while True:
            active = (self._force_auto or self.cfg.auto_copy)
            if not active:
                await asyncio.sleep(5)
                continue

            try:
                await self._consume_queue()
            except Exception as e:
                logger.error(f"[AUTO] Error: {e}", exc_info=True)

            scan_iv = self.cfg.get("SCAN_INTERVAL_SECONDS", 30)
            await asyncio.sleep(scan_iv)

    async def _consume_queue(self):
        """
        Read new lines from copy_queue.jsonl using a byte-offset cursor.
        Never re-reads old tasks, never misses new ones.
        """
        if not QUEUE_PATH.exists():
            return

        cursor = int(CURSOR_PATH.read_text()) if CURSOR_PATH.exists() else 0

        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            f.seek(cursor)
            new_lines = f.readlines()
            new_cursor = f.tell()

        if not new_lines:
            return

        CURSOR_PATH.write_text(str(new_cursor))

        for raw in new_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                task = json.loads(raw)
            except json.JSONDecodeError:
                continue

            task_id = task.get("task_id", raw[:40])
            if task_id in self._seen_tasks:
                continue
            self._seen_tasks.add(task_id)

            # Only copy if wallet is in auto_wallets list
            wallet_addr = task.get("wallet", "").lower()
            wallet_cfg  = next(
                (w for w in self.cfg.auto_wallets if w["address"] == wallet_addr),
                None,
            )
            if wallet_cfg is None:
                # Wallet not in current auto list — skip
                logger.debug(f"[AUTO] Task wallet {wallet_addr[:14]} not in auto_wallets, skip")
                continue

            await self._execute_trade(
                source      = "AUTO",
                wallet_addr = wallet_addr,
                volume_usdc = wallet_cfg["volume_usdc"],
                outcome     = task.get("outcome", "YES"),
                price       = float(task.get("price", 0.5)),
                whale_size  = float(task.get("whale_size_usdc", 0)),
                market      = task.get("market", ""),
                question    = task.get("question", ""),
                token_id    = task.get("token_id", ""),
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  MODE B — MANUAL COPY  (polls wallets in ## Manual Wallets section)
    # ─────────────────────────────────────────────────────────────────────────
    async def _manual_mode_loop(self):
        logger.info(f"[MANUAL] Loop started")
        scan_iv = self.cfg.get("SCAN_INTERVAL_SECONDS", 30)

        while True:
            active = (self._force_manual or self.cfg.manual_copy)
            if not active or not self.cfg.manual_wallets:
                await asyncio.sleep(5)
                continue

            try:
                await self._poll_manual_wallets()
            except Exception as e:
                logger.error(f"[MANUAL] Error: {e}", exc_info=True)

            scan_iv = self.cfg.get("SCAN_INTERVAL_SECONDS", 30)
            await asyncio.sleep(scan_iv)

    async def _poll_manual_wallets(self):
        now     = int(time.time())
        wallets = self.cfg.manual_wallets
        if not wallets:
            return

        logger.debug(f"[MANUAL] Polling {len(wallets)} wallets...")

        for wallet in wallets:
            addr      = wallet["address"]
            since_ts  = self._last_polled.get(addr, now - 120)

            try:
                trades = await self.client.get_wallet_activity(addr, limit=20)
            except Exception as e:
                logger.debug(f"[MANUAL] poll {addr[:14]}: {e}")
                continue

            new_trades = [
                t for t in (trades or [])
                if int(t.get("timestamp", t.get("createdAt", 0)) or 0) > since_ts
                and t.get("side", "BUY").upper() == "BUY"
                and float(t.get("usdcSize", t.get("size", 0)) or 0) >= 10
            ]

            for t in new_trades:
                outcome  = "YES" if str(t.get("outcomeIndex", t.get("outcome", ""))) in ("0","yes","YES") else "NO"
                price    = float(t.get("price", 0.5) or 0.5)
                size     = float(t.get("usdcSize", t.get("size", 0)) or 0)
                market   = t.get("market", t.get("conditionId", ""))
                token_id = t.get("tokenId", t.get("asset", ""))
                question = t.get("title", t.get("question", market[:30]))

                await self._execute_trade(
                    source      = "MANUAL",
                    wallet_addr = addr,
                    volume_usdc = wallet["volume_usdc"],
                    outcome     = outcome,
                    price       = price,
                    whale_size  = size,
                    market      = market,
                    question    = question,
                    token_id    = token_id,
                )

            self._last_polled[addr] = now
            await asyncio.sleep(0.3)  # rate-limit between wallets

    # ─────────────────────────────────────────────────────────────────────────
    #  EXECUTE TRADE  (shared by AUTO + MANUAL)
    # ─────────────────────────────────────────────────────────────────────────
    async def _execute_trade(
        self,
        source:      str,
        wallet_addr: str,
        volume_usdc: float,
        outcome:     str,
        price:       float,
        whale_size:  float,
        market:      str,
        question:    str,
        token_id:    str,
    ):
        # ── Pre-flight checks ─────────────────────────────
        min_spread = self.cfg.get("MIN_SPREAD", 0.05)
        if 1.0 - price < min_spread:
            self._stats["skipped"] += 1
            logger.debug(f"[{source}] Skip: spread {1-price:.3f} < {min_spread}")
            return

        max_budget = self.cfg.get("MAX_TOTAL_BUDGET", 500.0)
        max_mkt    = self.cfg.get("MAX_PER_MARKET", 100.0)
        my_vol     = min(volume_usdc, max_mkt)

        if self._deployed + my_vol > max_budget:
            self._stats["skipped"] += 1
            logger.warning(f"[{source}] Skip: budget ${self._deployed:.0f}/${max_budget}")
            return

        max_pos = self.cfg.get("MAX_OPEN_POSITIONS", 10)
        if len(self._open_positions) >= max_pos:
            self._stats["skipped"] += 1
            logger.warning(f"[{source}] Skip: max positions {max_pos}")
            return

        src_color = Fore.GREEN if source == "AUTO" else Fore.MAGENTA
        logger.info(
            f"\n{src_color}[{source}] 🔔 WHALE TRADE{Style.RESET_ALL}\n"
            f"   Wallet  : {wallet_addr[:16]}...\n"
            f"   Market  : {question[:62]}\n"
            f"   Outcome : {Fore.GREEN if outcome=='YES' else Fore.RED}{outcome}{Style.RESET_ALL} "
            f"@ {price:.4f}  whale=${whale_size:,.0f}\n"
            f"   Copying : ${my_vol:.2f} USDC"
        )

        # ── Human-lag delay ───────────────────────────────
        max_delay = self.cfg.get("MAX_COPY_DELAY_SECONDS", 10)
        delay     = max(1, abs(hash(token_id + outcome)) % (max_delay + 1))
        await asyncio.sleep(delay)

        # ── Refresh live price ────────────────────────────
        best_ask = await self.client.get_best_ask(token_id)
        if best_ask:
            price = min(best_ask * 1.005, 0.99)

        # ── Place order ───────────────────────────────────
        ok, result = await self._place_order(token_id, my_vol, price)

        if ok:
            self._deployed += my_vol
            self._open_positions[result] = {
                "order_id":  result,
                "token_id":  token_id,
                "question":  question[:50],
                "outcome":   outcome,
                "size":      my_vol,
                "price":     price,
                "source":    source,
                "wallet":    wallet_addr,
                "opened_at": time.time(),
            }
            if source == "AUTO":
                self._stats["auto_copied"] += 1
            else:
                self._stats["manual_copied"] += 1
            logger.info(f"  ↳ {Fore.GREEN}✓ ORDER PLACED  {result[:24]}...{Style.RESET_ALL}")
        else:
            logger.error(f"  ↳ {Fore.RED}✗ FAILED: {result}{Style.RESET_ALL}")

    # ─────────────────────────────────────────────────────────────────────────
    #  ORDER PLACEMENT  (EIP-712 sign → CLOB submit)
    # ─────────────────────────────────────────────────────────────────────────
    async def _place_order(
        self,
        token_id:   str,
        size_usdc:  float,
        price:      float,
    ) -> Tuple[bool, str]:
        balance = self.signer.usdc_balance()
        if balance < size_usdc:
            return False, f"Insufficient USDC: {balance:.2f} < {size_usdc:.2f}"

        try:
            price      = max(0.001, min(price, 0.999))
            shares     = size_usdc / price
            maker_amt  = int(size_usdc * 1e6)
            taker_amt  = int(shares   * 1e6)
            expiration = int(time.time()) + 86_400  # 24h

            order, sig = self.signer.sign_order(
                token_id     = token_id,
                side         = 0,  # BUY
                maker_amount = maker_amt,
                taker_amount = taker_amt,
                expiration   = expiration,
            )

            payload = {
                **{k: str(v) if isinstance(v, int) else v for k, v in order.items()},
                "signature": sig,
            }

            resp     = await self.client.post_order(payload)
            order_id = resp.get("orderID") or resp.get("id", "")
            error    = resp.get("error")  or resp.get("errorMsg", "")

            if error:
                return False, str(error)
            if order_id:
                return True, order_id
            return False, f"No orderID in response: {resp}"

        except Exception as e:
            return False, str(e)

    # ─────────────────────────────────────────────────────────────────────────
    #  STOP LOSS MONITOR
    # ─────────────────────────────────────────────────────────────────────────
    async def _stop_loss_loop(self):
        while True:
            await asyncio.sleep(30)
            if not self._open_positions:
                continue
            sl_pct = self.cfg.get("STOP_LOSS_PCT", 30.0) / 100
            for oid, pos in list(self._open_positions.items()):
                try:
                    bid = await self.client.get_best_bid(pos["token_id"])
                    if bid is None:
                        continue
                    if bid < pos["price"] * (1 - sl_pct):
                        logger.warning(
                            f"{Fore.RED}[SL] Stop loss triggered: "
                            f"{pos['question'][:40]}  "
                            f"entry={pos['price']:.3f}  bid={bid:.3f}{Style.RESET_ALL}"
                        )
                        await self._close_position(oid, pos, bid)
                except Exception as e:
                    logger.debug(f"[SL] {oid}: {e}")

    async def _close_position(self, order_id: str, pos: dict, bid: float):
        shares    = pos["size"] / pos["price"]
        maker_amt = int(shares       * 1e6)
        taker_amt = int(shares * bid * 1e6)

        try:
            order, sig = self.signer.sign_order(
                token_id     = pos["token_id"],
                side         = 1,  # SELL
                maker_amount = maker_amt,
                taker_amount = taker_amt,
                expiration   = int(time.time()) + 3600,
            )
            payload = {
                **{k: str(v) if isinstance(v, int) else v for k, v in order.items()},
                "signature": sig,
            }
            await self.client.post_order(payload)
        except Exception as e:
            logger.warning(f"[SL] Sell order error: {e}")

        pnl = (bid - pos["price"]) * shares
        self._stats["pnl"] += pnl
        self._stats["wins" if pnl >= 0 else "losses"] += 1
        self._deployed = max(0.0, self._deployed - pos["size"])
        del self._open_positions[order_id]
        pnl_c = Fore.GREEN if pnl >= 0 else Fore.RED
        logger.info(f"[SL] Closed  PnL: {pnl_c}{pnl:+.2f} USDC{Style.RESET_ALL}")

    # ─────────────────────────────────────────────────────────────────────────
    #  STATS LOOP  (every 5 min)
    # ─────────────────────────────────────────────────────────────────────────
    async def _stats_loop(self):
        while True:
            await asyncio.sleep(300)
            self._print_stats()

    def _print_stats(self):
        s     = self._stats
        total = s["wins"] + s["losses"]
        wr    = f"{s['wins']/total*100:.0f}%" if total > 0 else "—"
        up    = int(time.time() - self._start_ts)
        hh, mm = divmod(up // 60, 60)
        pnl_c = Fore.GREEN if s["pnl"] >= 0 else Fore.RED

        logger.info(
            f"\n{Fore.CYAN}── AGENT 2 STATS  (uptime {hh}h{mm:02d}m) ─────────────────{Style.RESET_ALL}\n"
            f"  AUTO  mode : {self.cfg.auto_copy_str}  "
            f"(auto_wallets={len(self.cfg.auto_wallets)})\n"
            f"  MANUAL mode: {self.cfg.manual_copy_str}  "
            f"(manual_wallets={len(self.cfg.manual_wallets)})\n"
            f"  Auto copied  : {s['auto_copied']}\n"
            f"  Manual copied: {s['manual_copied']}\n"
            f"  Win/Loss     : {s['wins']}/{s['losses']}  ({wr})\n"
            f"  PnL          : {pnl_c}{s['pnl']:+.2f} USDC{Style.RESET_ALL}\n"
            f"  Deployed     : ${self._deployed:.2f}\n"
            f"  Open pos.    : {len(self._open_positions)}\n"
            f"  Skipped      : {s['skipped']}\n"
            f"{Fore.CYAN}──────────────────────────────────────────────────────{Style.RESET_ALL}"
        )

    def print_status(self):
        self._print_stats()
        if self._open_positions:
            print(f"\n{Fore.CYAN}Open Positions:{Style.RESET_ALL}")
            for oid, pos in self._open_positions.items():
                src_c = Fore.GREEN if pos["source"] == "AUTO" else Fore.MAGENTA
                print(
                    f"  [{src_c}{pos['source']}{Style.RESET_ALL}] "
                    f"{pos['outcome']}  ${pos['size']:.0f}  "
                    f"@ {pos['price']:.3f}  {pos['question'][:40]}"
                )

    def _print_banner(self):
        print(f"\n{Fore.CYAN}{'═'*65}")
        print(f"  AGENT 2 — COPY TRADER")
        print(f"  Wallet: {WALLET_ADDR[:16]}...")
        print(f"  AUTO   mode: {self.cfg.auto_copy_str}  "
              f"→  {len(self.cfg.auto_wallets)} wallets from Agent 1")
        print(f"  MANUAL mode: {self.cfg.manual_copy_str}  "
              f"→  {len(self.cfg.manual_wallets)} wallets manual")
        print(f"  Budget: ${self.cfg.get('MAX_TOTAL_BUDGET',500):.0f}  "
              f"max/trade: ${self.cfg.get('MAX_PER_MARKET',100):.0f}  "
              f"SL: {self.cfg.get('STOP_LOSS_PCT',30):.0f}%")
        print(f"{'═'*65}{Style.RESET_ALL}\n")

    async def close(self):
        await self.client.close()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    p = argparse.ArgumentParser(description="Agent 2 — Copy Trader")
    p.add_argument("--auto",   action="store_true", help="Force AUTO mode on (ignore wallet.md setting)")
    p.add_argument("--manual", action="store_true", help="Force MANUAL mode on (ignore wallet.md setting)")
    p.add_argument("--status", action="store_true", help="Print status then exit")
    args = p.parse_args()

    agent = CopyTraderAgent(
        force_auto   = args.auto,
        force_manual = args.manual,
    )
    try:
        if args.status:
            agent.cfg.load()
            agent.print_status()
            return
        await agent.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass  # Ctrl+C — thoát sạch
    finally:
        logger.info("Agent 2 stopped.")
        await agent.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
