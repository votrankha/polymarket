"""
╔══════════════════════════════════════════════════════════════════╗
║  AGENT 1 - Whale Hunter   (Standalone, no dependency on Agent 2) ║
║                                                                  ║
║  Pipeline:                                                       ║
║  [S1] WebSocket trade stream → detect trade > $10k              ║
║       └─ fallback: REST poll every 60s                           ║
║                        │                                         ║
║  [S2] History Analyzer  (Gamma Activity API)                     ║
║       └─ win_rate · avg_size · volume · diversity                ║
║                        │                                         ║
║  [S3] Wallet Scorer     (reads criterion.md)                     ║
║       └─ Kelly · bot-filter · insider-filter → score 0-1        ║
║                        │                                         ║
║       score < min  → DISCARD                                     ║
║       score >= min → TRACKED DB (shared/db/tracked_wallets.json) ║
║                        │                                         ║
║  [S4] Realtime Tracker  (poll every 20s)                         ║
║       └─ new whale trade → push → shared/copy_queue.jsonl       ║
║                                                                  ║
║  [REPORT] Mỗi 1 giờ:                                            ║
║       └─ shared/reports/whale_report_YYYY-MM-DD_HH.md           ║
║       └─ agent2_copy_trader/wallet.md  (auto-updated)           ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python agent1_whale_hunter.py             # run forever (recommended)
    python agent1_whale_hunter.py --bootstrap # seed DB from leaderboard, exit
    python agent1_whale_hunter.py --status    # print DB summary, exit
    python agent1_whale_hunter.py --report    # force-write report now, exit
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from colorama import Fore, Style, init
from dotenv import load_dotenv

# ── Root ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Load .env TRƯỚC KHI đọc bất kỳ os.getenv nào ─────────────────────────────
load_dotenv(ROOT / "shared" / ".env", override=True)  # override=True: agent1 luôn thắng

# ── Filter rules - auto-generated từ criterion.md bởi criterion_compiler ──
# Import động: tự reload khi filter_rules.py thay đổi
try:
    from agent1_whale_hunter.criterion_compiler import load_filter_rules, compile_criterion
except ImportError:
    from criterion_compiler import load_filter_rules, compile_criterion

from shared.polymarket_client import PolymarketClient, TradeStream
from shared.db_store import get_db

# ── Logging ───────────────────────────────────────────────────────────────────
init(autoreset=True)
(ROOT / "shared").mkdir(parents=True, exist_ok=True)

# LOG_LEVEL từ .env: DEBUG để xem WS raw, INFO để chạy bình thường
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
_log_fmt    = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

class _FlushFileHandler(logging.FileHandler):
    """FileHandler flush ngay sau mỗi record - không mất log khi crash."""
    def emit(self, record):
        super().emit(record)
        self.flush()

# Chỉ setup handlers 1 lần - tránh duplicate khi module bị import lại
# propagate=False: không đẩy lên root logger (tránh in 2-3 lần)
logger = logging.getLogger("agent1")
if not logger.handlers:
    logger.setLevel(getattr(logging, _log_level, logging.INFO))
    logger.propagate = False

    _sh = logging.StreamHandler()
    _sh.setFormatter(_log_fmt)
    logger.addHandler(_sh)

    _fh = _FlushFileHandler(ROOT / "shared" / "agent1.log", encoding="utf-8", mode="a")
    _fh.setFormatter(_log_fmt)
    logger.addHandler(_fh)

# ── Paths ─────────────────────────────────────────────────────────────────────
CRITERION_FILE  = ROOT / "agent1_whale_hunter" / "criterion.md"
WALLET_MD       = ROOT / "agent2_copy_trader"  / "wallet.md"
REPORTS_DIR     = ROOT / "shared" / "reports"
DB_PATH         = ROOT / "shared" / "db" / "polybot.db"
QUEUE_PATH      = ROOT / "shared" / "copy_queue.jsonl"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Env (đọc SAU load_dotenv) ─────────────────────────────────────────────────
REPORT_INTERVAL_H  = float(os.getenv("REPORT_INTERVAL_HOURS",  "24"))
MIN_DETECT_SIZE    = float(os.getenv("MIN_DETECT_SIZE",         "10000"))
HISTORY_BATCH      = int(os.getenv("HISTORY_BATCH",             "6"))
TRACKING_INTERVAL  = int(os.getenv("TRACKING_INTERVAL",         "20"))
BOOTSTRAP_LIMIT    = int(os.getenv("BOOTSTRAP_LIMIT",           "150"))


# ══════════════════════════════════════════════════════════════════════════════
#  CRITERION READER
#  Agent đọc file này mỗi lần khởi động - thay đổi criterion.md không cần
#  restart, chỉ cần đợi vòng lặp tiếp theo của report_loop.
# ══════════════════════════════════════════════════════════════════════════════
def read_criterion() -> dict:
    """
    Load filter_rules từ filter_rules.py (đã được compile thủ công hoặc tự động).
    criterion.md chỉ đọc để log, không compile vì đã có filter_rules.
    """
    try:
        # compile_criterion()  # ĐÃ TẮT: không cần Anthropic API, đã hand-code
        rules = load_filter_rules()
        cfg   = rules.describe()
    except Exception as e:
        logger.warning(f"[criterion] Load error: {e} - using defaults")
        cfg = {
            "min_win_rate": 60.0, "min_history_days": 120, "max_trades_per_month": 100,
            "min_markets_played": 10, "min_kelly": 0.05, "min_spread": 0.05,
        }
    logger.info(
        f"{Fore.CYAN}[criterion.md → filter_rules.py]  "
        f"{cfg}  "
        f"| .env detect≥${MIN_DETECT_SIZE:,.0f}{Style.RESET_ALL}"
    )
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
#  TRACKED WALLETS DB (SQLite)
# ══════════════════════════════════════════════════════════════════════════════
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set

class TrackedWalletsDB:
    def __init__(self):
        self._db_path = DB_PATH
        self._conn = sqlite3.connect(self._db_path)
        self._cursor = self._conn.cursor()
        self._create_table_if_not_exists()

    def _create_table_if_not_exists(self):
        self._cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_snapshots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                address          TEXT NOT NULL,
                ts               INTEGER NOT NULL,
                score            REAL,
                win_rate         REAL,
                kelly            REAL,
                net_pnl          REAL,
                avg_size         REAL,
                total_closed     INTEGER,
                trades_per_month REAL,
                account_age_days INTEGER,
                total_volume     REAL,
                market_count     INTEGER,
                bot_flag         INTEGER DEFAULT 0,
                specialist       INTEGER DEFAULT 0,
                source           TEXT DEFAULT 'scan'
            )
        ''')
        self._conn.commit()

    def upsert(self, entry: dict):
        addr = entry["address"].lower()
        now  = int(time.time())
        
        # Get existing data
        self._cursor.execute('''
            SELECT * FROM wallet_snapshots WHERE address = ?
            ORDER BY ts DESC LIMIT 1
        ''', (addr,))
        existing = self._cursor.fetchone()
        
        # Update or insert
        if existing:
            # Update latest snapshot with new data and current timestamp
            self._cursor.execute('''
                UPDATE wallet_snapshots 
                SET score = ?, win_rate = ?, kelly = ?, net_pnl = ?, 
                    avg_size = ?, total_closed = ?, trades_per_month = ?, 
                    account_age_days = ?, total_volume = ?, market_count = ?, bot_flag = ?, 
                    specialist = ?, ts = ?
                WHERE address = ? AND ts = ?
            ''', (
                entry.get('score'),
                entry.get('win_rate'),
                entry.get('kelly'),
                entry.get('net_pnl'),
                entry.get('avg_size'),
                entry.get('total_closed'),
                entry.get('trades_per_month'),
                entry.get('account_age_days'),
                entry.get('total_volume'),
                entry.get('market_count', 0),
                entry.get('high_price_entry_ratio', 0.0),
                1 if entry.get('bot_flag') else 0,
                1 if entry.get('specialist') else 0,
                now,  # update ts to now
                addr,
                existing[2]  # old ts
            ))
        else:
            # Insert new
            self._cursor.execute('''
                INSERT INTO wallet_snapshots 
                (address, ts, score, win_rate, kelly, net_pnl, avg_size, total_closed,
                 trades_per_month, account_age_days, total_volume, market_count, 
                 high_price_entry_ratio, bot_flag, specialist, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                addr,
                now,
                entry.get('score'),
                entry.get('win_rate'),
                entry.get('kelly'),
                entry.get('net_pnl'),
                entry.get('avg_size'),
                entry.get('total_closed'),
                entry.get('trades_per_month'),
                entry.get('account_age_days'),
                entry.get('total_volume'),
                entry.get('market_count', 0),
                entry.get('high_price_entry_ratio', 0.0),
                1 if entry.get('bot_flag') else 0,
                1 if entry.get('specialist') else 0,
                entry.get('source', 'scan')
            ))
        
        self._conn.commit()

    def update_last_trade(self, address: str, timestamp: int):
        """Refresh last trade timestamp for a tracked wallet (preserves other fields)."""
        addr = address.lower()
        existing = self.get(addr)
        if existing:
            entry = dict(existing)
            entry["ts"] = timestamp
            self.upsert(entry)

    def remove(self, address: str) -> bool:
        addr = address.lower()
        self._cursor.execute('DELETE FROM wallet_snapshots WHERE address = ?', (addr,))
        self._conn.commit()
        return self._cursor.rowcount > 0

    def get(self, address: str) -> Optional[dict]:
        addr = address.lower()
        self._cursor.execute('''
            SELECT * FROM wallet_snapshots 
            WHERE address = ? 
            ORDER BY ts DESC 
            LIMIT 1
        ''', (addr,))
        row = self._cursor.fetchone()
        if not row:
            return None
        
        # Map row to dict (must match table schema exactly)
        columns = ['id', 'address', 'ts', 'score', 'win_rate', 'kelly', 'net_pnl',
                   'avg_size', 'total_closed', 'trades_per_month', 'account_age_days',
                   'total_volume', 'market_count', 'high_price_entry_ratio',
                   'bot_flag', 'specialist', 'source']
        return dict(zip(columns, row))

    def all(self) -> List[dict]:
        """Return latest snapshot for each tracked wallet."""
        self._cursor.execute('''
            SELECT w.* FROM wallet_snapshots w
            INNER JOIN (
                SELECT address, MAX(ts) as max_ts
                FROM wallet_snapshots
                GROUP BY address
            ) m ON w.address = m.address AND w.ts = m.max_ts
            ORDER BY w.score DESC
        ''')
        rows = self._cursor.fetchall()
        columns = ['id', 'address', 'ts', 'score', 'win_rate', 'kelly', 'net_pnl',
                   'avg_size', 'total_closed', 'trades_per_month', 'account_age_days',
                   'total_volume', 'market_count', 'bot_flag', 'specialist', 'source']
        return [dict(zip(columns, row)) for row in rows]

    def addresses(self) -> Set[str]:
        """Return set of all tracked wallet addresses (latest snapshot each)."""
        self._cursor.execute('''
            SELECT DISTINCT w.address FROM wallet_snapshots w
            INNER JOIN (
                SELECT address, MAX(ts) as max_ts
                FROM wallet_snapshots
                GROUP BY address
            ) m ON w.address = m.address AND w.ts = m.max_ts
        ''')
        rows = self._cursor.fetchall()
        return {row[0] for row in rows}

    def __len__(self) -> int:
        """Count of tracked wallets."""
        self._cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT DISTINCT w.address FROM wallet_snapshots w
                INNER JOIN (
                    SELECT address, MAX(ts) as max_ts
                    FROM wallet_snapshots
                    GROUP BY address
                ) m ON w.address = m.address AND w.ts = m.max_ts
            )
        ''')
        return self._cursor.fetchone()[0]

    def print_summary(self):
        rows = self.all()
        print(f"\n{Fore.CYAN}{'─'*90}")
        print(f"  TRACKED WALLETS DB  ·  {len(rows)} wallets")
        print(f"{'─'*90}{Style.RESET_ALL}")
        print(f"  {'ADDRESS':<42} {'SCORE':>5} {'WR':>6} {'KELLY':>6} {'AVG_SZ':>9} {'AGE':>5} {'NOTE'}")
        print(f"  {'─'*42} {'─'*5} {'─'*6} {'─'*6} {'─'*9} {'─'*5}")
        for w in rows[:25]:
            tag = "⭐" if w.get("kelly", 0) >= 0.15 else "  "
            print(
                f"  {w['address']}  "
                f"{w.get('score',0):>5.2f} "
                f"{w.get('win_rate',0):>5.1f}% "
                f"{w.get('kelly',0):>6.3f}{tag} "
                f"${w.get('avg_size',0):>8,.0f} "
                f"{w.get('account_age_days',0):>4}d  "
                f"{str(w.get('notes',''))[:30]}" 
            )
        if len(rows) > 25:
            print(f"  ... and {len(rows)-25} more wallets")
        print(f"{Fore.CYAN}{'─'*90}{Style.RESET_ALL}\n")

    def close(self):
        self._conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  COPY TASK QUEUE  (Agent 2 polls this file)
# ══════════════════════════════════════════════════════════════════════════════
class CopyQueue:
    def push(self, task: dict):
        task.setdefault("task_id",    f"{int(time.time()*1000)}_{task.get('wallet','')[:8]}")
        task.setdefault("created_at", int(time.time()))
        with open(QUEUE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(task) + "\n")
        logger.info(
            f"{Fore.GREEN}[QUEUE ▶] {task.get('outcome','')} "
            f"${task.get('whale_size_usdc',0):,.0f}  "
            f"{task.get('question','')[:50]}{Style.RESET_ALL}"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 2  -  HISTORY ANALYZER
# ══════════════════════════════════════════════════════════════════════════════
def analyze_history(trades: List[dict], now_ts: int,
                    closed_positions: List[dict] = None) -> dict:
    """
    Phân tích lịch sử ví dựa trên:
    - trades: dùng để tính age, volume, bot detection, trades_per_month
    - closed_positions: dùng để tính win/loss/kelly (chính xác hơn vì có realizedPnl sẵn)

    Polymarket resolve positions tự động (không qua SELL) nên không thể tính
    win/loss từ trades. /closed-positions là nguồn đúng duy nhất.
    """
    if not trades and not closed_positions:
        return {}

    # ── Thống kê từ trades (age, volume, bot detection) ──────────────────────
    ts_key   = lambda t: int(t.get("timestamp", t.get("createdAt", 0)) or 0)
    total_vol  = 0.0
    all_ts: List[int] = []
    all_sizes: List[float] = []
    cats: Set[str] = set()
    mkt_ids: Set[str] = set()

    for t in (trades or []):
        side   = t.get("side", "BUY").upper()
        usdc   = float(t.get("usdcSize", 0) or 0)
        shares = float(t.get("size", 0) or 0)
        price  = float(t.get("price", 0) or 0)
        if usdc <= 0:
            usdc = shares * price
        mkt_id = t.get("conditionId", t.get("market", ""))
        ts     = int(t.get("timestamp", t.get("createdAt", 0)) or 0)

        if usdc <= 0:
            continue

        total_vol += usdc
        if ts:
            all_ts.append(ts)
        if mkt_id:
            mkt_ids.add(mkt_id)
        if side == "BUY":
            all_sizes.append(usdc)

    n_trades = len(trades) if trades else 0
    if all_ts:
        first_ts         = min(all_ts)
        account_age_days = max(1, (now_ts - first_ts) // 86400)
    else:
        account_age_days = 1

    months           = max(1.0, account_age_days / 30.0)
    trades_per_month = n_trades / months
    avg_size         = total_vol / n_trades if n_trades > 0 else 0.0

    # --- High entry price ratio (BOND_TRADER detection) ---
    high_price_entry_trades = 0
    total_buy_trades = 0
    for t in (trades or []):
        if t.get("side", "").upper() == "BUY":
            total_buy_trades += 1
            price = float(t.get("price", 0) or 0)
            if price > 0.90:
                high_price_entry_trades += 1
    high_price_entry_ratio = (
        high_price_entry_trades / total_buy_trades
    ) if total_buy_trades > 0 else 0.0

    # ── Win/Loss từ closed_positions (nguồn chính xác) ───────────────────────
    wins, losses = 0, 0
    win_pnls: List[float] = []
    loss_pnls: List[float] = []
    net_pnl = 0.0

    for pos in (closed_positions or []):
        pnl = float(pos.get("realizedPnl", 0) or 0)
        net_pnl += pnl
        if pnl >= 0:
            wins += 1
            win_pnls.append(pnl)
        else:
            losses += 1
            loss_pnls.append(abs(pnl))
        # Bổ sung market count từ closed positions
        cid = pos.get("conditionId", "")
        if cid:
            mkt_ids.add(cid)

    total_closed = wins + losses
    win_rate     = (wins / total_closed * 100) if total_closed > 0 else 0.0

    # ── Kelly  f* = (p·b - q) / b ────────────────────────────────────────────
    avg_win  = sum(win_pnls)  / len(win_pnls)  if win_pnls  else 1.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 1.0
    b        = avg_win / avg_loss if avg_loss > 0 else 1.0
    p        = win_rate / 100
    kelly    = max(0.0, (p * b - (1 - p)) / b) if b > 0 else 0.0

    # ── Bot detection ─────────────────────────────────────────────────────────

    # [1] Round sizes: > 95% trades là bội số 100 USDC chính xác (relaxed from 90%)
    bot_round = False
    if all_sizes:
        round_n   = sum(1 for s in all_sizes if round(s) % 100 == 0)
        bot_round = (round_n / len(all_sizes)) > 0.98

    # [2] Regular intervals: CV < 10% → robot clock
    bot_interval = False
    if len(all_ts) >= 10:
        ts_sorted = sorted(all_ts)
        ivs = [ts_sorted[i+1] - ts_sorted[i]
               for i in range(len(ts_sorted)-1)
               if ts_sorted[i+1] > ts_sorted[i]]
        if len(ivs) >= 5:
            mu  = sum(ivs) / len(ivs)
            std = (sum((x - mu)**2 for x in ivs) / len(ivs))**0.5
            bot_interval = (mu > 0 and std / mu < 0.30)  # relaxed further to 0.30

    # [3] High frequency: > 200 trades/month (relaxed from 100)
    bot_hf = trades_per_month > 300

    # [4] Latency sniper: exploit 15-min crypto markets bằng cách vào trong
    #     30-90 giây trước khi market close (lag giữa real price và Polymarket)
    #     Dấu hiệu: nhiều trades timestamp rất gần market expiry window
    #     Proxy: nếu > 60% trades trong 1 ngày tập trung vào ≤ 3 giờ → sniper pattern
    bot_latency_sniper = False
    if len(all_ts) >= 20:
        # Đếm số trades theo giờ trong ngày (UTC hour)
        from collections import Counter
        hour_counts = Counter(
            (ts % 86400) // 3600   # giờ UTC trong ngày
            for ts in all_ts
        )
        total_ts = len(all_ts)
        top3_hours = sum(sorted(hour_counts.values(), reverse=True)[:3])
        # > 85% trades tập trung vào 3 giờ cố định → latency sniper (relaxed from 70%)
        if top3_hours / total_ts > 0.85:
            bot_latency_sniper = True

    # [5] Micro-trade spam: avg size < $5 với > 200 trades/month → noise trader / wash
    bot_micro = (avg_size < 5.0 and trades_per_month > 200)

    bot_flag = bot_round or bot_interval or bot_hf or bot_latency_sniper or bot_micro

    # ── Insider / suspicious ──────────────────────────────────────────────────
    sus_flag   = (total_closed < 10 and avg_size > 5_000) or (win_rate > 90 and total_closed > 30)
    sus_reason = (
        "new_account+large_size" if total_closed < 10 and avg_size > 5_000 else
        "win_rate>90%"           if win_rate > 90 and total_closed > 30    else ""
    )

    return {
        "win_rate":           round(win_rate, 2),
        "total_trades":       n_trades,
        "total_closed":       total_closed,
        "wins":               wins,
        "losses":             losses,
        "net_pnl":            round(net_pnl, 2),
        "total_volume":       round(total_vol, 2),
        "avg_size":           round(avg_size, 2),
        "trades_per_month":   round(trades_per_month, 2),
        "account_age_days":   account_age_days,
        "kelly":              round(kelly, 4),
        "kelly_b":            round(b, 3),
        "category_diversity": len(cats),
        "markets_count":      len(mkt_ids),  # fixed key name (was market_count)
        "bot_flag":           bot_flag,
        "bot_round":          bot_round,
        "bot_interval":       bot_interval,
        "bot_hf":             bot_hf,
        "bot_latency_sniper": bot_latency_sniper,
        "bot_micro":          bot_micro,
        "high_price_entry_ratio": round(high_price_entry_ratio, 4),
        "suspicious_flag":    sus_flag,
        "suspicious_reason":  sus_reason,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 3  -  WALLET SCORER
# ══════════════════════════════════════════════════════════════════════════════
def score_wallet(stats: dict, cfg: dict) -> Tuple[float, str]:
    """
    Delegate hoàn toàn cho filter_rules.py.
    Trả về (score, reason). Nếu reason == "SPECIALIST", wallet là specialist whale.
    """
    if not stats:
        return 0.0, "no_data"

    try:
        rules = load_filter_rules()
        passed, reason = rules.evaluate(stats)
        if not passed:
            return 0.0, reason
        score = round(float(rules.score(stats)), 4)
        # Nếu là specialist, giữ reason "SPECIALIST" để agent1 xử lý sau
        return score, reason if reason else ""
    except Exception as e:
        logger.warning(f"[score_wallet] filter_rules error: {e} - fallback to hardcode")
        # Fallback an toàn
        if stats.get("bot_flag"):
            return 0.0, "BOT"
        if stats.get("win_rate", 0) < 60:
            return 0.0, f"low_wr:{stats.get('win_rate',0):.1f}%"
        if stats.get("account_age_days", 0) < 120:
            return 0.0, f"too_new:{stats.get('account_age_days',0)}d"
        if stats.get("kelly", 0) < 0.05:
            return 0.0, f"low_kelly:{stats.get('kelly',0):.4f}"
        return 0.5, ""


# ══════════════════════════════════════════════════════════════════════════════
#  HOURLY REPORT + wallet.md UPDATER
# ══════════════════════════════════════════════════════════════════════════════
def write_report(db: TrackedWalletsDB, reason: str = "scheduled") -> Path:
    """
    Xuất báo cáo markdown và cập nhật wallet.md.
    Gọi mỗi REPORT_INTERVAL_H giờ (mặc định 1h).
    """
    now     = datetime.now(timezone.utc)
    ts_str  = now.strftime("%Y-%m-%d_%H")
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    path    = REPORTS_DIR / f"whale_report_{ts_str}.md"

    wallets = sorted(db.all(), key=lambda w: w.get("score", 0), reverse=True)

    # ── Markdown report ───────────────────────────────────
    lines = [
        f"# Whale Report - {now_str}",
        f"> Trigger: `{reason}` · Agent 1 standalone",
        "",
        "## Summary",
        f"- Wallets tracked : **{len(wallets)}**",
        f"- High Kelly (≥0.15): **{sum(1 for w in wallets if w.get('kelly',0) >= 0.15)}**",
        "",
        "## Tracked Wallets",
        "",
        "| # | Wallet | Score | Win Rate | Kelly | Avg Size | Age | Volume | Notes |",
        "|---|--------|-------|----------|-------|----------|-----|--------|-------|",
    ]

    for i, w in enumerate(wallets, 1):
        star = "⭐" if w.get("kelly", 0) >= 0.15 else ""
        lines.append(
            f"| {i} "
            f"| `{w['address']}` "
            f"| **{w.get('score',0):.2f}** "
            f"| {w.get('win_rate',0):.1f}% "
            f"| {w.get('kelly',0):.3f}{star} "
            f"| ${w.get('avg_size',0):,.0f} "
            f"| {w.get('account_age_days',0)}d "
            f"| ${w.get('total_volume',0)/1000:.0f}K "
            f"| {str(w.get('notes',''))[:40]} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"{Fore.GREEN}[REPORT] Written: {path.name}  ({len(wallets)} wallets){Style.RESET_ALL}")

    # ── Update wallet.md ─────────────────────────────────
    _update_wallet_md(wallets, now_str)

    return path


def _update_wallet_md(wallets: List[dict], now_str: str):
    """
    Ghi lại section '## Active Wallets' trong wallet.md.
    Giữ nguyên tất cả section khác (Global Settings, Manual, Blacklist).
    """
    try:
        text  = WALLET_MD.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Build new active block
        new_active_block = [
            f"# [Agent1 auto-update] {now_str}  ({len(wallets)} wallets)",
        ]
        for w in wallets:
            # Volume per trade: scale with kelly
            vol = 50 if w.get("kelly", 0) >= 0.15 else 25
            new_active_block.append(
                f"{w['address']} | {vol} | all | "
                f"score={w.get('score',0):.2f} "
                f"kelly={w.get('kelly',0):.3f} "
                f"wr={w.get('win_rate',0):.1f}%"
            )

        # Splice into wallet.md
        out: List[str] = []
        in_active = False
        replaced  = False
        for line in lines:
            if line.strip().startswith("## Active Wallets"):
                out.append(line)
                out.extend(new_active_block)
                in_active = True
                replaced  = True
                continue
            if in_active and line.startswith("##"):
                in_active = False
            if not in_active:
                out.append(line)

        if not replaced:
            # Section not found - append at end
            out.append("\n## Active Wallets")
            out.extend(new_active_block)

        WALLET_MD.write_text("\n".join(out), encoding="utf-8")
        logger.info(f"[wallet.md] Updated - {len(wallets)} wallets")

    except Exception as e:
        logger.error(f"[wallet.md] Update failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT 1 - ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════
class WhaleHunterAgent:

    def __init__(self):
        self.client  = PolymarketClient()
        self.db      = TrackedWalletsDB()
        self.queue   = CopyQueue()
        self.cfg: dict = {}
        
        # Close database when agent closes
        import atexit
        atexit.register(self.db.close)

        # SQLite DB - lưu lịch sử trade, snapshots, copy results
        self.store = get_db()
        _db_s = self.store.get_stats()
        logger.info(
            f"[db_store] whale_trades={_db_s.get('whale_trades',0)}  "
            f"snapshots={_db_s.get('wallet_snapshots',0)}  "
            f"copy_trades={_db_s.get('copy_trades',0)}  "
            f"({_db_s.get('db_size_mb',0):.1f}MB)"
        )

        # Stage 1 → Stage 2/3
        self._candidate_q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._analyzing:   Set[str]      = set()
        self._ws_seen:     deque         = deque(maxlen=50_000)

        # Stats (reset each hour for report)
        self._session_start = time.time()
        self._stats = dict(
            ws_events=0, candidates=0,
            analyzed=0, promoted=0, discarded=0,
            copy_tasks=0,
        )
        # Track additions this reporting period
        self._added_this_period:   List[str] = []
        self._removed_this_period: List[str] = []

    def _append_to_wallet_md(self, address: str, is_specialist: bool, note: str):
        """Append promoted wallet to Active Wallets section in wallet.md."""
        addr_lower = address.lower()
        # Read existing addresses from Active Wallets section (lines with pipe)
        existing = set()
        try:
            with open(WALLET_MD, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 1:
                            existing.add(parts[0].strip().lower())
        except FileNotFoundError:
            existing = set()
        if addr_lower in existing:
            return
        # Budget: specialist 200, normal 100 (matching historical usage 50? use 100 for now)
        budget = 200 if is_specialist else 100
        category = "all"
        entry = f"{addr_lower} | {budget} | {category} | {note}"
        try:
            with open(WALLET_MD, "a") as f:
                f.write(entry + "\n")
            logger.info(f"  {Fore.CYAN}[WALLET.MD] Added {addr_lower[:10]}... (budget=${budget}, {note}){Style.RESET_ALL}")
        except Exception as e:
            logger.warning(f"[WALLET.MD] Write failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  STAGE 1  -  WebSocket scanner  (+  REST fallback)
    # ─────────────────────────────────────────────────────────────────────────
    async def _stage1_ws(self):
        """
        Stage 1: Detect large trades bằng REST polling data-api /trades.

        WS (ws-subscriptions-clob) chỉ push orderbook snapshots/changes -
        KHÔNG push last_trade_price theo thời gian thực đủ để dùng.
        Approach đúng (theo top_trader.py): poll REST mỗi POLL_INTERVAL giây,
        track seen txHash để dedup.
        """
        POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds
        logger.info(
            f"{Fore.CYAN}[S1] Trade scanner starting "
            f"(min_size=${MIN_DETECT_SIZE:,.0f}, poll={POLL_INTERVAL}s){Style.RESET_ALL}"
        )

        seen_tx: set = set()   # dedup bằng transactionHash
        MAX_SEEN = 5000        # giới hạn memory

        while True:
            try:
                trades = await self.client.get_large_trades(
                    min_size=MIN_DETECT_SIZE,
                    limit=100,
                )
                new_count = 0
                for t in trades:
                    tx   = t.get("transaction_hash", t.get("txHash", ""))
                    addr = t.get("trader_address", "")

                    # Dedup theo txHash nếu có, không thì dùng addr+timestamp
                    key = tx if tx else f"{addr}_{t.get('timestamp',0)}"
                    if key and key in seen_tx:
                        continue

                    if key:
                        seen_tx.add(key)
                        if len(seen_tx) > MAX_SEEN:
                            # Xóa 1000 entries cũ nhất
                            for _ in range(1000):
                                seen_tx.pop() if seen_tx else None

                    new_count += 1
                    await self._on_large_trade(t)

                if new_count:
                    logger.debug(f"[S1] Polled {len(trades)} trades, {new_count} new")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[S1/poll] {e}")

            await asyncio.sleep(POLL_INTERVAL)

    async def _on_large_trade(self, trade: dict):
        addr = (trade.get("trader_address") or trade.get("maker", "")).lower().strip()

        if not addr or not addr.startswith("0x"):
            return

        self._stats["ws_events"] += 1

        # Already in DB → just refresh last_trade_ts (Stage 4 will handle)
        if self.db.get(addr):
            self.db.update_last_trade(addr, trade.get("timestamp", int(time.time())))
            return

        # Dedup
        if addr in self._analyzing or addr in self._ws_seen:
            return
        self._ws_seen.append(addr)

        size = trade.get("size_usdc", float(trade.get("usdcSize", 0) or 0))
        logger.info(
            f"{Fore.YELLOW}[S1] ${size:,.0f}  {addr}  "
            f"{trade.get('outcome','')}  mkt:{trade.get('market','')[:22]}{Style.RESET_ALL}"
        )
        self._stats["candidates"] += 1
        await self._candidate_q.put({"address": addr, "trigger": trade})

    # ─────────────────────────────────────────────────────────────────────────
    #  STAGE 2 + 3  -  Analyzer + Scorer  (worker pool)
    # ─────────────────────────────────────────────────────────────────────────
    async def _stage23_worker(self, wid: int):
        while True:
            item = await self._candidate_q.get()
            addr = item["address"]
            if addr in self._analyzing:
                self._candidate_q.task_done()
                continue
            self._analyzing.add(addr)
            try:
                await self._analyze_and_score(addr, item.get("trigger"))
            except Exception as e:
                logger.error(f"[S2/S3 w{wid}] {addr}: {e}")
            finally:
                self._analyzing.discard(addr)
                self._candidate_q.task_done()

    async def _analyze_and_score(self, address: str, trigger: Optional[dict]):
        now_ts = int(time.time())

        # S2: fetch history - trades (age/volume/bot) + closed_positions (win/loss)
        logger.info(f"  {Fore.CYAN}[S2] {address}{Style.RESET_ALL}")
        trades, closed = await asyncio.gather(
            self.client.get_wallet_activity(address, limit=500),
            self.client.get_closed_positions(address, limit=500),
        )
        self._stats["analyzed"] += 1

        if not trades and not closed:
            self._stats["discarded"] += 1
            logger.debug(f"  [S3] DISCARD {address} → no_data")
            return

        logger.debug(
            f"  [S2] {address}  trades={len(trades or [])}  closed={len(closed or [])}"
        )
        try:
            stats = analyze_history(trades or [], now_ts, closed_positions=closed or [])
        except Exception as e:
            logger.error(f"[S2] analyze_history error for {address}: {e}")
            self._stats["discarded"] += 1
            return

        # ── Lưu trade history vào SQLite ─────────────────────────────────────
        if trades:
            n_new = self.store.save_whale_trades(address, trades, source="s2")
            if n_new > 0:
                logger.debug(f"  [DB] +{n_new} trades saved for {address[:10]}...")

        # ── Lưu closed_positions - PnL thực tế từng market đã resolve ────────
        # Trước đây chỉ dùng để tính score rồi bỏ → giờ persist vào DB
        if closed:
            n_cp = self.store.save_closed_positions(address, closed)
            if n_cp > 0:
                logger.debug(f"  [DB] +{n_cp} closed_positions saved for {address[:10]}...")

            # Xóa open_positions đã resolve (market trong closed không còn open)
            for pos in closed:
                mkt = pos.get("conditionId") or pos.get("market_id", "")
                out = pos.get("outcome") or ("YES" if str(pos.get("outcomeIndex","0"))=="0" else "NO")
                if mkt:
                    self.store.remove_closed_open_position(address, mkt, out)

        # S3: score
        try:
            score, reject = score_wallet(stats, self.cfg)
        except Exception as e:
            logger.error(f"[S3] score_wallet error for {address}: {e}")
            self._stats["discarded"] += 1
            return

        # Xử lý SPECIALIST: nếu reason == "SPECIALIST", treat as pass và đánh dấu
        is_specialist = False
        if reject == "SPECIALIST":
            reject = ""
            is_specialist = True

        if reject:
            self._stats["discarded"] += 1
            logger.info(f"  {Fore.RED}[S3] DISCARD {address} → {reject}{Style.RESET_ALL}")
            return

        # Promoted
        self._stats["promoted"] += 1
        if is_specialist:
            note = "SPECIALIST"
        elif trigger:
            note = f"detected via ${trigger.get('size_usdc',0):,.0f} trade"
        else:
            note = "bootstrap"
        # Build entry dict for DB
        entry = {
            "address": address,
            "score": score,
            "specialist": 1 if is_specialist else 0,
            "source": "bootstrap" if not trigger else "scan",
            **stats
        }
        self.db.upsert(entry)
        self._append_to_wallet_md(address, is_specialist, note)
        self._added_this_period.append(address)

        # Lưu snapshot để theo dõi performance theo thời gian
        self.store.save_wallet_snapshot(
            address, stats, score,
            source="bootstrap" if not trigger else "scan"
        )

        logger.info(
            f"  {Fore.GREEN}[S3] ✓ PROMOTED {address}  "
            f"score={score:.2f}  wr={stats['win_rate']:.1f}%  "
            f"kelly={stats['kelly']:.3f}  age={stats['account_age_days']}d{Style.RESET_ALL}"
        )

        logger.info(
            f"  {Fore.GREEN}[S3] ✓ PROMOTED {address}  "
            f"score={score:.2f}  wr={stats['win_rate']:.1f}%  "
            f"kelly={stats['kelly']:.3f}  age={stats['account_age_days']}d{Style.RESET_ALL}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  STAGE 4  -  Realtime tracker → push CopyTask
    # ─────────────────────────────────────────────────────────────────────────
    async def _stage4_tracker(self):
        logger.info(f"{Fore.CYAN}[S4] Tracker started (poll {TRACKING_INTERVAL}s){Style.RESET_ALL}")
        last_polled: Dict[str, int] = {}

        while True:
            wallets = self.db.all()
            if not wallets:
                await asyncio.sleep(TRACKING_INTERVAL)
                continue

            now = int(time.time())

            for i in range(0, len(wallets), HISTORY_BATCH):
                chunk = wallets[i : i + HISTORY_BATCH]
                results = await asyncio.gather(
                    *[self._poll_wallet(w, last_polled.get(w["address"], now - TRACKING_INTERVAL * 2))
                      for w in chunk],
                    return_exceptions=True,
                )
                for wallet, new_trades in zip(chunk, results):
                    if not isinstance(new_trades, list):
                        continue
                    for trade in new_trades:
                        await self._emit_copy_task(wallet, trade)
                    if new_trades:
                        last_polled[wallet["address"]] = now
                await asyncio.sleep(0.4)

            await asyncio.sleep(TRACKING_INTERVAL)

    async def _poll_wallet(self, wallet: dict, since_ts: int) -> List[dict]:
        trades = await self.client.get_wallet_activity(wallet["address"], limit=20)
        if not trades:
            return []
        return [
            t for t in trades
            if int(t.get("timestamp", t.get("createdAt", 0)) or 0) > since_ts
            and t.get("side", "BUY").upper() == "BUY"
            and float(t.get("usdcSize", t.get("size", 0)) or 0) >= 100
        ]

    async def _emit_copy_task(self, wallet: dict, trade: dict):
        price    = float(trade.get("price", 0.5) or 0.5)
        size     = float(trade.get("usdcSize", trade.get("size", 0)) or 0)
        market   = trade.get("market", trade.get("conditionId", ""))
        token_id = trade.get("tokenId", trade.get("asset", ""))
        question = trade.get("title", trade.get("question", market[:30]))
        outcome  = (
            "YES" if str(trade.get("outcomeIndex", trade.get("outcome", "")))
            in ("0", "yes", "YES") else "NO"
        )

        if 1.0 - price < self.cfg.get("min_spread", 0.05):
            return  # price too close to resolution, skip

        self._stats["copy_tasks"] += 1

        # Lưu trade realtime vào SQLite (source='s4')
        self.store.save_whale_trades(wallet["address"], [{
            "transactionHash": trade.get("transactionHash", trade.get("txHash",
                f"{wallet['address']}_{int(time.time())}_{price}")),
            "conditionId": market,
            "title": question,
            "outcome": outcome,
            "price": str(price),
            "usdcSize": str(size),
            "side": "BUY",
            "timestamp": str(trade.get("timestamp", int(time.time()))),
        }], source="s4")

        # Cache market metadata nếu chưa có
        if market and not self.store.get_market(market):
            self.store.upsert_market(market, {
                "question": question,
                "category": trade.get("category", ""),
            }, ttl_seconds=3600)

        # ── Lưu open_position hiện tại của ví ───────────────────────────────
        # Dùng để: phát hiện average-down, unrealized PnL dashboard
        try:
            open_pos = await self.client.get_open_positions(wallet["address"], limit=100)
            if open_pos:
                self.store.save_open_positions(wallet["address"], open_pos)
                logger.debug(f"  [DB] {len(open_pos)} open_positions saved for {wallet['address'][:10]}...")
        except Exception as _e:
            logger.debug(f"  [DB] open_positions fetch skip: {_e}")

        # is_new_position: True = lần đầu mua market này, False = average down
        _is_new = self.store.is_new_position(wallet["address"], market, outcome)
        if not _is_new:
            logger.debug(f"  [S4] {wallet['address'][:10]} averaging down on {market[:16]} - still emitting")

        self.queue.push({
            "wallet":          wallet["address"],
            "wallet_score":    wallet.get("score", 0),
            "is_new_position": _is_new,
            "wallet_win_rate": wallet.get("win_rate", 0),
            "market":          market,
            "question":        question,
            "outcome":         outcome,
            "price":           price,
            "whale_size_usdc": size,
            "token_id":        token_id,
            "signal_strength": None,
            "source":          "agent1_track",
        })

    # ─────────────────────────────────────────────────────────────────────────
    #  HOURLY REPORT LOOP
    # ─────────────────────────────────────────────────────────────────────────
    async def _report_loop(self):
        """
        Mỗi REPORT_INTERVAL_H giờ:
          1. Re-read criterion.md (cập nhật config động)
          2. Xuất whale_report_YYYY-MM-DD_HH.md
          3. Cập nhật wallet.md cho Agent 2
          4. In stats
          5. Reset added/removed tracking
        """
        # First report right after bootstrap
        await asyncio.sleep(5)
        write_report(self.db, reason="startup")
        self._stats_print()
        self._added_this_period   = []
        self._removed_this_period = []

        while True:
            interval_s = REPORT_INTERVAL_H * 3600
            logger.info(f"[REPORT] Next report in {REPORT_INTERVAL_H:.1f}h")
            await asyncio.sleep(interval_s)

            # Re-read criterion.md every cycle
            try:
                self.cfg = read_criterion()
            except Exception as e:
                logger.warning(f"[REPORT] Failed re-reading criterion.md: {e}")

            write_report(
                self.db,
                reason=f"scheduled ({REPORT_INTERVAL_H:.0f}h)"
            )
            self._stats_print()
            self._added_this_period   = []
            self._removed_this_period = []

    # ─────────────────────────────────────────────────────────────────────────
    #  BOOTSTRAP  (seed DB from leaderboard on first run)
    # ─────────────────────────────────────────────────────────────────────────
    async def _bootstrap(self):
        if len(self.db) > 0:
            logger.info(f"[BOOTSTRAP] DB already has {len(self.db)} wallets - skip")
            return

        logger.info(f"{Fore.CYAN}[BOOTSTRAP] Empty DB - seeding from leaderboard...{Style.RESET_ALL}")
        leaderboard = await self.client.get_leaderboard(limit=BOOTSTRAP_LIMIT + 100)

        addresses = list({
            (e.get("address") or e.get("proxyWallet") or e.get("user", "")).lower()
            for e in leaderboard
        })
        addresses = [a for a in addresses if a.startswith("0x")]
        addresses = addresses[:BOOTSTRAP_LIMIT]

        logger.info(f"[BOOTSTRAP] Evaluating {len(addresses)} addresses …")

        for i in range(0, len(addresses), HISTORY_BATCH):
            chunk = addresses[i : i + HISTORY_BATCH]
            await asyncio.gather(
                *[self._analyze_and_score(a, None) for a in chunk],
                return_exceptions=True,
            )
            await asyncio.sleep(0.8)

        logger.info(
            f"{Fore.GREEN}[BOOTSTRAP] Done - {len(self.db)} wallets promoted{Style.RESET_ALL}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  STATS
    # ─────────────────────────────────────────────────────────────────────────
    def _stats_print(self):
        s     = self._stats
        up    = int(time.time() - self._session_start)
        hh,mm = divmod(up // 60, 60)
        # Lấy DB stats để hiển thị cùng agent stats
        _db_s = self.store.get_stats()
        logger.info(
            f"\n{Fore.CYAN}── AGENT 1 STATS  (uptime {hh}h{mm:02d}m) ─────────────{Style.RESET_ALL}\n"
            f"  [S1] Trades detected     : {s['ws_events']}\n"
            f"  [S1] Candidates queued  : {s['candidates']}\n"
            f"  [S2] Analyzed           : {s['analyzed']}\n"
            f"  [S3] Promoted to DB     : {s['promoted']}\n"
            f"  [S3] Discarded          : {s['discarded']}\n"
            f"  [S4] Copy tasks emitted : {s['copy_tasks']}\n"
            f"       DB size            : {len(self.db)}\n"
            f"  [SQLite] whale_trades={_db_s.get('whale_trades',0)}  "
            f"snapshots={_db_s.get('wallet_snapshots',0)}  "
            f"copy_trades={_db_s.get('copy_trades',0)}  "
            f"({_db_s.get('db_size_mb',0):.1f}MB)\n"
            f"{Fore.CYAN}──────────────────────────────────────────────────{Style.RESET_ALL}"
        )

        # Cleanup expired market cache mỗi lần print stats (mỗi giờ)
        self.store.cleanup_expired_markets()

    # ─────────────────────────────────────────────────────────────────────────
    #  PUBLIC ENTRY POINTS
    # ─────────────────────────────────────────────────────────────────────────
    async def run(self):
        """Full pipeline - runs forever, completely independent of Agent 2."""
        print(f"\n{Fore.GREEN}{'═'*65}")
        print(f"  AGENT 1 - WHALE HUNTER   (standalone)")
        print(f"  Report every {REPORT_INTERVAL_H:.0f}h  ·  "
              f"Scan every {TRACKING_INTERVAL}s")
        print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'═'*65}{Style.RESET_ALL}\n")

        self.cfg = read_criterion()
        await self._bootstrap()
        self.db.print_summary()

        try:
            await asyncio.gather(
                self._stage1_ws(),
                *[self._stage23_worker(i) for i in range(HISTORY_BATCH)],
                self._stage4_tracker(),
                self._report_loop(),
            )
        except asyncio.CancelledError:
            pass  # normal shutdown via Ctrl+C

    async def run_bootstrap_only(self):
        """Seed DB from leaderboard then exit."""
        self.cfg = read_criterion()
        await self._bootstrap()
        write_report(self.db, reason="bootstrap")
        self.db.print_summary()
        self._stats_print()

    async def run_report_only(self):
        """Force-write report from current DB then exit."""
        self.cfg = read_criterion()
        write_report(self.db, reason="manual")
        self.db.print_summary()

    async def close(self):
        await self.client.close()


# ── Entry ──────────────────────────────────────────────────────────────────────
async def main():
    p = argparse.ArgumentParser(description="Agent 1 - Whale Hunter")
    p.add_argument("--bootstrap", action="store_true", help="Seed DB then exit")
    p.add_argument("--status",    action="store_true", help="Print DB summary then exit")
    p.add_argument("--report",    action="store_true", help="Force write report then exit")
    args = p.parse_args()

    agent = WhaleHunterAgent()
    try:
        if args.status:
            agent.db.print_summary()
            agent._stats_print()
        elif args.bootstrap:
            await agent.run_bootstrap_only()
        elif args.report:
            await agent.run_report_only()
        else:
            await agent.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass  # Ctrl+C - thoát sạch không in traceback
    finally:
        logger.info(f"Agent 1 stopped.")
        await agent.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # bắt lần cuối nếu Python 3.12 raise lên tới đây
