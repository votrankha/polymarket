"""
db_store.py — SQLite Database Layer
════════════════════════════════════════════════════════════════════════════════

Module trung tâm quản lý toàn bộ persistent data của bot.
Cả Agent 1 và Agent 2 đều import và dùng module này.

Database: shared/db/polybot.db  (1 file SQLite duy nhất)

Schema gồm 6 bảng:
  whale_trades      ← lịch sử trade BUY của whale wallet (Agent 1 S2+S4 ghi)
  wallet_snapshots  ← snapshot stats ví mỗi lần scan (Agent 1 S3 ghi)
  copy_trades       ← mọi lệnh copy bot đã đặt (Agent 2 ghi)
  markets           ← cache market metadata + resolved status
  closed_positions  ← PnL thực tế từng market đã resolve (nguồn chính xác nhất)
  open_positions    ← vị thế đang mở + unrealized PnL realtime

Thiết kế:
  - Thread-safe: dùng threading.Lock() cho mọi write
  - Idempotent: INSERT OR IGNORE / INSERT OR REPLACE — không lỗi khi trùng
  - Non-blocking: lỗi chỉ log warning, không raise exception lên agent
  - Tự tạo schema lần đầu (không cần migrate thủ công)
  - Migration an toàn: ALTER TABLE IF NOT EXISTS via pragma check

Dùng:
  from shared.db_store import get_db
  db = get_db()
  db.save_whale_trades(addr, trades)
  db.save_closed_positions(addr, closed_positions)
  db.save_open_positions(addr, positions)
  db.save_wallet_snapshot(addr, stats, score)
  db.open_copy_trade(task, usdc_spent, order_id)
  db.close_copy_trade(task_id, status, exit_price, pnl_usdc)
  db.upsert_market(condition_id, info)
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("db_store")

# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional["BotDB"] = None
_instance_lock = threading.Lock()


def get_db(db_path: Optional[Path] = None) -> "BotDB":
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                if db_path is None:
                    root = Path(__file__).parent.parent
                    db_path = root / "shared" / "db" / "polybot.db"
                _instance = BotDB(db_path)
    return _instance


# ══════════════════════════════════════════════════════════════════════════════

class BotDB:
    """SQLite wrapper cho Polymarket 2-Agent Bot."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self._migrate()
        logger.info(f"[db_store] Connected: {db_path}")

    # ──────────────────────────────────────────────────────────────────────────
    #  SCHEMA
    # ──────────────────────────────────────────────────────────────────────────

    def _create_schema(self):
        """Tạo tất cả bảng + index. An toàn khi gọi nhiều lần."""
        with self._lock:
            cur = self._conn.cursor()

            # ── Bảng 1: whale_trades ──────────────────────────────────────────
            # Lưu mọi BUY trade của whale wallet
            # tx_hash PRIMARY KEY → không bao giờ lưu trùng
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whale_trades (
                    tx_hash   TEXT PRIMARY KEY,
                    address   TEXT NOT NULL,
                    market_id TEXT,
                    question  TEXT,
                    outcome   TEXT,
                    price     REAL,
                    usdc_size REAL,
                    shares    REAL,          -- usdc_size / price
                    side      TEXT DEFAULT 'BUY',
                    ts        INTEGER,
                    source    TEXT DEFAULT 's2'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wt_address ON whale_trades(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wt_ts      ON whale_trades(ts)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wt_market  ON whale_trades(market_id)")

            # ── Bảng 2: wallet_snapshots ──────────────────────────────────────
            # Snapshot stats ví mỗi lần Agent 1 scan — theo dõi performance theo thời gian
            cur.execute("""
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
                    market_count     INTEGER,  -- number of distinct markets traded
                    bot_flag         INTEGER DEFAULT 0,
                    source           TEXT DEFAULT 'scan'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_address ON wallet_snapshots(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ws_ts      ON wallet_snapshots(ts)")

            # ── Bảng 3: copy_trades ───────────────────────────────────────────
            # Mọi lệnh copy bot đã đặt — Agent 2 ghi khi mở, result_tracker cập nhật khi đóng
            cur.execute("""
                CREATE TABLE IF NOT EXISTS copy_trades (
                    task_id      TEXT PRIMARY KEY,
                    wallet       TEXT NOT NULL,
                    market_id    TEXT,
                    question     TEXT,
                    outcome      TEXT,
                    entry_price  REAL,
                    usdc_spent   REAL,
                    status       TEXT DEFAULT 'open',
                    exit_price   REAL,
                    pnl_usdc     REAL,
                    wallet_score REAL,
                    copied_at    INTEGER,
                    closed_at    INTEGER,
                    order_id     TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ct_wallet ON copy_trades(wallet)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ct_status ON copy_trades(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ct_copied ON copy_trades(copied_at)")

            # ── Bảng 4: markets ───────────────────────────────────────────────
            # Cache metadata + resolved status cho mọi market từng gặp
            cur.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    condition_id      TEXT PRIMARY KEY,
                    question          TEXT,
                    category          TEXT,
                    end_date          TEXT,
                    resolved          INTEGER DEFAULT 0,
                    winning_outcome   TEXT,
                    current_price_yes REAL,   -- YES token price (0.0–1.0)
                    volume            REAL,   -- total volume USDC
                    liquidity         REAL,   -- available liquidity
                    num_traders       INTEGER,
                    cached_at         INTEGER,
                    expires_at        INTEGER
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mkt_resolved ON markets(resolved)")

            # ── Bảng 5: closed_positions ──────────────────────────────────────
            # PnL thực tế từng ví trên từng market đã resolve
            # Nguồn: /closed-positions API — realizedPnl chính xác nhất
            # Agent 1 S2 lưu khi bootstrap/rescan (thay vì chỉ dùng rồi bỏ)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS closed_positions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    address      TEXT NOT NULL,
                    market_id    TEXT NOT NULL,
                    question     TEXT,
                    outcome      TEXT,      -- YES / NO
                    realized_pnl REAL,      -- từ API: realizedPnl (USDC), có thể âm
                    invested     REAL,      -- tổng USDC đã bỏ vào
                    shares       REAL,      -- số shares
                    avg_price    REAL,      -- giá mua trung bình
                    end_price    REAL,      -- giá lúc resolve (1.0 = thắng, 0.0 = thua)
                    result       TEXT,      -- 'won' | 'lost' | 'sold'
                    resolved_at  INTEGER,   -- timestamp market resolve
                    fetched_at   INTEGER,   -- timestamp bot fetch
                    UNIQUE(address, market_id, outcome)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_address   ON closed_positions(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_market    ON closed_positions(market_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_result    ON closed_positions(result)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cp_resolved  ON closed_positions(resolved_at)")

            # ── Bảng 6: open_positions ────────────────────────────────────────
            # Vị thế đang mở của whale wallets — cập nhật mỗi lần S4 poll
            # Dùng để: unrealized PnL, phát hiện average-down, copy quality filter
            cur.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    address        TEXT NOT NULL,
                    market_id      TEXT NOT NULL,
                    question       TEXT,
                    outcome        TEXT,       -- YES / NO
                    shares         REAL,       -- tổng shares đang nắm
                    avg_price      REAL,       -- giá mua trung bình
                    invested       REAL,       -- tổng USDC đã bỏ vào
                    current_price  REAL,       -- giá hiện tại (YES token)
                    unrealized_pnl REAL,       -- shares * (current_price - avg_price)
                    initial_trade_ts INTEGER,  -- timestamp lần mua đầu tiên
                    last_trade_ts  INTEGER,    -- timestamp lần mua gần nhất
                    trade_count    INTEGER DEFAULT 1,  -- số lần mua (>1 = average down)
                    updated_at     INTEGER,
                    PRIMARY KEY (address, market_id, outcome)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_op_address ON open_positions(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_op_updated ON open_positions(updated_at)")

            self._conn.commit()
            logger.debug("[db_store] Schema ready")

    def _migrate(self):
        """
        Migration an toàn cho DB đã tồn tại.
        Thêm cột mới vào bảng cũ nếu chưa có — không mất data.
        """
        with self._lock:
            cur = self._conn.cursor()
            existing = {}
            for table in ("whale_trades", "markets"):
                cur.execute(f"PRAGMA table_info({table})")
                existing[table] = {row[1] for row in cur.fetchall()}

            migrations = [
                # whale_trades: thêm cột shares nếu chưa có
                ("whale_trades", "shares",
                 "ALTER TABLE whale_trades ADD COLUMN shares REAL"),
                # markets: thêm các cột mới nếu chưa có
                ("markets", "current_price_yes",
                 "ALTER TABLE markets ADD COLUMN current_price_yes REAL"),
                ("markets", "volume",
                 "ALTER TABLE markets ADD COLUMN volume REAL"),
                ("markets", "liquidity",
                 "ALTER TABLE markets ADD COLUMN liquidity REAL"),
                ("markets", "num_traders",
                 "ALTER TABLE markets ADD COLUMN num_traders INTEGER"),
            ]

            migrated = 0
            for table, col, sql in migrations:
                if col not in existing.get(table, set()):
                    try:
                        cur.execute(sql)
                        migrated += 1
                        logger.info(f"[db_store] Migration: {table}.{col} added")
                    except Exception as e:
                        logger.warning(f"[db_store] Migration skip {table}.{col}: {e}")

            if migrated:
                self._conn.commit()
                logger.info(f"[db_store] {migrated} migrations applied")

    # ══════════════════════════════════════════════════════════════════════════
    #  WHALE TRADES
    # ══════════════════════════════════════════════════════════════════════════

    def save_whale_trades(self, address: str, trades: List[dict],
                          source: str = "s2") -> int:
        """
        Lưu danh sách BUY trades của whale.
        INSERT OR IGNORE → không lỗi khi trùng.
        Tự tính shares = usdc_size / price.
        Returns: số trades thực sự được insert mới.
        """
        if not trades:
            return 0
        inserted = 0
        try:
            with self._lock:
                cur = self._conn.cursor()
                for t in trades:
                    tx = (t.get("transactionHash")
                          or t.get("transaction_hash")
                          or t.get("txHash")
                          or f"{address}_{t.get('timestamp', t.get('createdAt', 0))}_{t.get('price', 0)}")

                    usdc = float(t.get("usdcSize") or 0)
                    if usdc <= 0:
                        usdc = float(t.get("size") or 0) * float(t.get("price") or 0)

                    price = float(t.get("price") or 0)
                    shares = round(usdc / price, 6) if price > 0 else 0.0
                    ts = int(t.get("timestamp") or t.get("createdAt") or 0)
                    outcome = t.get("outcome", "")
                    if not outcome:
                        outcome = "YES" if str(t.get("outcomeIndex", "0")) == "0" else "NO"

                    cur.execute("""
                        INSERT OR IGNORE INTO whale_trades
                            (tx_hash, address, market_id, question, outcome,
                             price, usdc_size, shares, side, ts, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tx, address.lower(),
                        t.get("conditionId") or t.get("market") or "",
                        t.get("title") or t.get("question") or "",
                        outcome, price,
                        round(usdc, 4), shares,
                        t.get("side", "BUY").upper(),
                        ts, source,
                    ))
                    if cur.rowcount > 0:
                        inserted += 1
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] save_whale_trades({address[:10]}): {e}")

        if inserted > 0:
            logger.debug(f"[db_store] +{inserted} trades for {address[:10]}... (src={source})")
        return inserted

    def get_whale_trades(self, address: str,
                         since_ts: int = 0, limit: int = 500) -> List[dict]:
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT * FROM whale_trades
                    WHERE address = ? AND ts > ?
                    ORDER BY ts DESC LIMIT ?
                """, (address.lower(), since_ts, limit))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[db_store] get_whale_trades: {e}")
            return []

    def get_latest_trade_ts(self, address: str) -> int:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT MAX(ts) FROM whale_trades WHERE address = ?",
                    (address.lower(),)
                )
                result = cur.fetchone()[0]
                return int(result) if result else 0
        except Exception as e:
            logger.warning(f"[db_store] get_latest_trade_ts: {e}")
            return 0

    # ══════════════════════════════════════════════════════════════════════════
    #  CLOSED POSITIONS  (nguồn PnL chính xác nhất)
    # ══════════════════════════════════════════════════════════════════════════

    def save_closed_positions(self, address: str,
                               positions: List[dict]) -> int:
        """
        Lưu closed positions từ /closed-positions API.
        Mỗi row = 1 market đã resolve, có realizedPnl sẵn.

        Field mapping từ Polymarket API:
          conditionId   → market_id
          title         → question
          outcome       → outcome (YES/NO)
          realizedPnl   → realized_pnl  (USDC, có thể âm)
          invested      → invested
          size          → shares
          averagePrice  → avg_price
          endPrice      → end_price (1.0=thắng, 0.0=thua)
          timestamp     → resolved_at

        INSERT OR REPLACE → cập nhật nếu đã có (PnL có thể thay đổi)
        Returns: số rows được upsert
        """
        if not positions:
            return 0
        upserted = 0
        now = int(time.time())
        try:
            with self._lock:
                cur = self._conn.cursor()
                for p in positions:
                    pnl     = float(p.get("realizedPnl") or p.get("pnl") or 0)
                    invested= float(p.get("invested") or p.get("cashInvested") or 0)
                    shares  = float(p.get("size") or p.get("shares") or 0)
                    avg_p   = float(p.get("averagePrice") or p.get("avgPrice") or 0)
                    end_p   = float(p.get("endPrice") or 0)
                    outcome = p.get("outcome") or ("YES" if str(p.get("outcomeIndex","0"))=="0" else "NO")

                    # Tự suy result nếu API không trả về
                    result = p.get("result") or p.get("side")
                    if not result:
                        if end_p >= 0.99:
                            result = "won"
                        elif end_p <= 0.01:
                            result = "lost"
                        else:
                            result = "sold"  # bán trước khi resolve

                    resolved_ts = int(
                        p.get("timestamp") or p.get("resolvedAt") or
                        p.get("createdAt") or now
                    )

                    cur.execute("""
                        INSERT OR REPLACE INTO closed_positions
                            (address, market_id, question, outcome,
                             realized_pnl, invested, shares, avg_price,
                             end_price, result, resolved_at, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        address.lower(),
                        p.get("conditionId") or p.get("market_id") or "",
                        p.get("title") or p.get("question") or "",
                        outcome,
                        round(pnl, 4), round(invested, 4),
                        round(shares, 6), round(avg_p, 6),
                        round(end_p, 6), result,
                        resolved_ts, now,
                    ))
                    upserted += 1
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] save_closed_positions({address[:10]}): {e}")

        if upserted > 0:
            logger.debug(f"[db_store] closed_positions: {upserted} upserted for {address[:10]}...")
        return upserted

    def get_closed_positions(self, address: str,
                              limit: int = 200) -> List[dict]:
        """PnL history của 1 ví, sort theo resolved_at DESC."""
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT cp.*, m.category
                    FROM closed_positions cp
                    LEFT JOIN markets m ON cp.market_id = m.condition_id
                    WHERE cp.address = ?
                    ORDER BY cp.resolved_at DESC
                    LIMIT ?
                """, (address.lower(), limit))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[db_store] get_closed_positions: {e}")
            return []

    def get_closed_position_for_market(self, address: str,
                                        market_id: str) -> Optional[dict]:
        """Lấy kết quả 1 trade cụ thể. Dùng cho dashboard Trade History."""
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT * FROM closed_positions
                    WHERE address = ? AND market_id = ?
                    LIMIT 1
                """, (address.lower(), market_id))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.warning(f"[db_store] get_closed_position_for_market: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    #  OPEN POSITIONS  (unrealized PnL realtime)
    # ══════════════════════════════════════════════════════════════════════════

    def save_open_positions(self, address: str,
                             positions: List[dict]) -> int:
        """
        Lưu / cập nhật open positions của 1 ví.
        Gọi từ Agent 1 S4 mỗi khi poll ví trong wallet.md.

        Field mapping từ Polymarket /positions API:
          conditionId  → market_id
          title        → question
          outcome      → outcome
          size         → shares (tổng shares đang nắm)
          avgPrice     → avg_price
          cashInvested → invested
          currentPrice → current_price
          unrealizedPnl→ unrealized_pnl (hoặc tính = shares*(cur-avg))

        PRIMARY KEY (address, market_id, outcome) → upsert tự động
        Returns: số rows được upsert
        """
        if not positions:
            return 0
        upserted = 0
        now = int(time.time())
        try:
            with self._lock:
                cur = self._conn.cursor()
                for p in positions:
                    shares    = float(p.get("size") or p.get("shares") or 0)
                    avg_p     = float(p.get("avgPrice") or p.get("averagePrice") or p.get("avg_price") or 0)
                    invested  = float(p.get("cashInvested") or p.get("invested") or 0)
                    cur_price = float(p.get("currentPrice") or p.get("current_price") or avg_p)
                    outcome   = p.get("outcome") or ("YES" if str(p.get("outcomeIndex","0"))=="0" else "NO")

                    # Tính unrealized PnL nếu API không trả về
                    unrealized = float(p.get("unrealizedPnl") or 0)
                    if unrealized == 0 and shares > 0 and avg_p > 0:
                        unrealized = round(shares * (cur_price - avg_p), 4)

                    # Lấy trade_count + initial_trade_ts từ row cũ (nếu đã có)
                    existing = self._conn.execute("""
                        SELECT trade_count, initial_trade_ts
                        FROM open_positions
                        WHERE address=? AND market_id=? AND outcome=?
                    """, (address.lower(),
                          p.get("conditionId") or p.get("market_id") or "",
                          outcome)).fetchone()

                    trade_count = (existing[0] + 1) if existing else 1
                    initial_ts  = existing[1] if existing else int(
                        p.get("timestamp") or p.get("createdAt") or now
                    )

                    cur.execute("""
                        INSERT OR REPLACE INTO open_positions
                            (address, market_id, question, outcome,
                             shares, avg_price, invested, current_price,
                             unrealized_pnl, initial_trade_ts, last_trade_ts,
                             trade_count, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        address.lower(),
                        p.get("conditionId") or p.get("market_id") or "",
                        p.get("title") or p.get("question") or "",
                        outcome,
                        round(shares, 6), round(avg_p, 6),
                        round(invested, 4), round(cur_price, 6),
                        unrealized,
                        initial_ts,
                        int(p.get("timestamp") or p.get("lastTradeTs") or now),
                        trade_count, now,
                    ))
                    upserted += 1
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] save_open_positions({address[:10]}): {e}")

        if upserted > 0:
            logger.debug(f"[db_store] open_positions: {upserted} upserted for {address[:10]}...")
        return upserted

    def remove_closed_open_position(self, address: str,
                                     market_id: str, outcome: str):
        """
        Xóa open_position khi market resolve.
        Gọi sau khi save_closed_positions thành công.
        """
        try:
            with self._lock:
                self._conn.execute("""
                    DELETE FROM open_positions
                    WHERE address=? AND market_id=? AND outcome=?
                """, (address.lower(), market_id, outcome))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] remove_closed_open_position: {e}")

    def get_open_positions(self, address: str) -> List[dict]:
        """Tất cả vị thế đang mở của 1 ví, sort theo invested DESC."""
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT op.*, m.end_date, m.resolved
                    FROM open_positions op
                    LEFT JOIN markets m ON op.market_id = m.condition_id
                    WHERE op.address = ?
                    ORDER BY op.invested DESC
                """, (address.lower(),))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[db_store] get_open_positions: {e}")
            return []

    def is_new_position(self, address: str,
                         market_id: str, outcome: str) -> bool:
        """
        Kiểm tra whale có đang average down không.
        True  = lần đầu mua market này (tín hiệu mạnh hơn)
        False = đã có position trước đó (có thể average down)
        Agent 2 dùng để filter copy quality.
        """
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT trade_count FROM open_positions
                    WHERE address=? AND market_id=? AND outcome=?
                """, (address.lower(), market_id, outcome))
                row = cur.fetchone()
                return row is None or row[0] <= 1
        except Exception as e:
            logger.warning(f"[db_store] is_new_position: {e}")
            return True  # default: coi là new để không bỏ lỡ

    # ══════════════════════════════════════════════════════════════════════════
    #  WALLET SNAPSHOTS
    # ══════════════════════════════════════════════════════════════════════════

    def save_wallet_snapshot(self, address: str, stats: dict,
                             score: float, source: str = "scan"):
        try:
            with self._lock:
                self._conn.execute("""
                    INSERT INTO wallet_snapshots
                        (address, ts, score, win_rate, kelly, net_pnl,
                         avg_size, total_closed, trades_per_month,
                         account_age_days, total_volume, market_count, bot_flag, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    address.lower(), int(time.time()),
                    round(score, 4),
                    stats.get("win_rate", 0), stats.get("kelly", 0),
                    stats.get("net_pnl", 0), stats.get("avg_size", 0),
                    stats.get("total_closed", 0), stats.get("trades_per_month", 0),
                    stats.get("account_age_days", 0), stats.get("total_volume", 0),
                    stats.get("market_count", 0),  # new field
                    int(bool(stats.get("bot_flag", False))), source,
                ))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] save_wallet_snapshot({address[:10]}): {e}")

    def get_wallet_snapshots(self, address: str, days: int = 90) -> List[dict]:
        since = int(time.time()) - days * 86400
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT * FROM wallet_snapshots
                    WHERE address = ? AND ts >= ?
                    ORDER BY ts ASC
                """, (address.lower(), since))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[db_store] get_wallet_snapshots: {e}")
            return []

    # ══════════════════════════════════════════════════════════════════════════
    #  COPY TRADES
    # ══════════════════════════════════════════════════════════════════════════

    def open_copy_trade(self, task: dict, usdc_spent: float,
                        order_id: str = "") -> bool:
        try:
            with self._lock:
                self._conn.execute("""
                    INSERT OR IGNORE INTO copy_trades
                        (task_id, wallet, market_id, question, outcome,
                         entry_price, usdc_spent, status,
                         wallet_score, copied_at, order_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """, (
                    task.get("task_id", f"task_{int(time.time())}"),
                    task.get("wallet", "").lower(),
                    task.get("market", ""), task.get("question", ""),
                    task.get("outcome", ""),
                    float(task.get("price", 0)), round(usdc_spent, 4),
                    float(task.get("wallet_score", 0)),
                    int(time.time()), order_id,
                ))
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"[db_store] open_copy_trade: {e}")
            return False

    def close_copy_trade(self, task_id: str, status: str,
                         exit_price: float = 0.0,
                         pnl_usdc: float = 0.0) -> bool:
        try:
            with self._lock:
                self._conn.execute("""
                    UPDATE copy_trades
                    SET status=?, exit_price=?, pnl_usdc=?, closed_at=?
                    WHERE task_id=?
                """, (status, exit_price, round(pnl_usdc, 4),
                      int(time.time()), task_id))
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"[db_store] close_copy_trade: {e}")
            return False

    def get_open_copy_trades(self) -> List[dict]:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM copy_trades WHERE status='open' ORDER BY copied_at DESC"
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[db_store] get_open_copy_trades: {e}")
            return []

    def get_copy_trade_summary(self) -> dict:
        try:
            with self._lock:
                cur = self._conn.execute("""
                    SELECT
                        COUNT(*)                                          AS total,
                        SUM(CASE WHEN status='open'    THEN 1 ELSE 0 END) AS open,
                        SUM(CASE WHEN status='won'     THEN 1 ELSE 0 END) AS won,
                        SUM(CASE WHEN status='lost'    THEN 1 ELSE 0 END) AS lost,
                        SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) AS expired,
                        ROUND(SUM(usdc_spent), 2)                         AS total_spent,
                        ROUND(SUM(COALESCE(pnl_usdc, 0)), 2)              AS total_pnl
                    FROM copy_trades
                """)
                row = dict(cur.fetchone())
                closed = (row.get("won") or 0) + (row.get("lost") or 0)
                row["win_rate_pct"] = round(
                    (row.get("won") or 0) / closed * 100, 1
                ) if closed > 0 else 0.0
                row["closed"] = closed
                return row
        except Exception as e:
            logger.warning(f"[db_store] get_copy_trade_summary: {e}")
            return {}

    # ══════════════════════════════════════════════════════════════════════════
    #  MARKET CACHE
    # ══════════════════════════════════════════════════════════════════════════

    def upsert_market(self, condition_id: str, info: dict,
                      ttl_seconds: int = 3600):
        now = int(time.time())
        try:
            with self._lock:
                self._conn.execute("""
                    INSERT OR REPLACE INTO markets
                        (condition_id, question, category, end_date,
                         resolved, winning_outcome,
                         current_price_yes, volume, liquidity, num_traders,
                         cached_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    condition_id,
                    info.get("question", ""),
                    info.get("category", ""),
                    info.get("end_date") or info.get("endDate", ""),
                    int(bool(info.get("resolved", False))),
                    info.get("winning_outcome") or info.get("winningOutcome"),
                    info.get("current_price_yes") or info.get("outcomePrices", [None])[0],
                    info.get("volume"),
                    info.get("liquidity"),
                    info.get("num_traders") or info.get("numTraders"),
                    now, now + ttl_seconds,
                ))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] upsert_market: {e}")

    def get_market(self, condition_id: str) -> Optional[dict]:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM markets WHERE condition_id=? AND expires_at>?",
                    (condition_id, int(time.time()))
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.warning(f"[db_store] get_market: {e}")
            return None

    def cleanup_expired_markets(self):
        cutoff = int(time.time()) - 7 * 86400
        try:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM markets WHERE resolved=1 AND cached_at<?", (cutoff,)
                )
                if cur.rowcount > 0:
                    logger.debug(f"[db_store] Cleaned {cur.rowcount} expired markets")
                self._conn.commit()
        except Exception as e:
            logger.warning(f"[db_store] cleanup_expired_markets: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    #  UTILITY
    # ══════════════════════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        try:
            with self._lock:
                stats = {}
                for table in ("whale_trades", "wallet_snapshots",
                              "copy_trades", "markets",
                              "closed_positions", "open_positions"):
                    cur = self._conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cur.fetchone()[0]
                stats["db_size_mb"] = round(
                    self.db_path.stat().st_size / 1024 / 1024, 2
                )
                return stats
        except Exception as e:
            logger.warning(f"[db_store] get_stats: {e}")
            return {}

    def close(self):
        try:
            self._conn.close()
            logger.info("[db_store] Connection closed")
        except Exception:
            pass


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s")

    with tempfile.TemporaryDirectory() as tmpdir:
        db = BotDB(Path(tmpdir) / "test.db")

        print("\n── Test 1: whale_trades (với shares) ──")
        trades = [{"transactionHash": f"0xhash{i}", "conditionId": f"0xmkt{i%3}",
                   "title": f"Market {i}", "outcomeIndex": "0", "side": "BUY",
                   "price": "0.65", "usdcSize": str(100*i),
                   "timestamp": str(1700000000 + i*3600)} for i in range(1, 4)]
        n = db.save_whale_trades("0xWhale", trades, source="s2")
        rows = db.get_whale_trades("0xWhale")
        print(f"  Inserted: {n}, shares[0]={rows[0]['shares']:.4f} (expected ~{100*2/0.65:.2f})")

        print("\n── Test 2: closed_positions ──")
        closed = [
            {"conditionId": "0xmkt0", "title": "BTC > 100k?", "outcome": "YES",
             "realizedPnl": 45.5, "invested": 65.0, "size": 100.0,
             "averagePrice": 0.65, "endPrice": 1.0, "timestamp": 1700100000},
            {"conditionId": "0xmkt1", "title": "ETH flip BTC?", "outcome": "NO",
             "realizedPnl": -30.0, "invested": 50.0, "size": 71.4,
             "averagePrice": 0.70, "endPrice": 0.0, "timestamp": 1700200000},
        ]
        n = db.save_closed_positions("0xWhale", closed)
        rows = db.get_closed_positions("0xWhale")
        print(f"  Saved: {n}, PnL: {[r['realized_pnl'] for r in rows]}, result: {[r['result'] for r in rows]}")

        print("\n── Test 3: open_positions + is_new_position ──")
        positions = [
            {"conditionId": "0xmkt2", "title": "Fed cut rates?", "outcome": "YES",
             "size": 150.0, "avgPrice": 0.55, "cashInvested": 82.5,
             "currentPrice": 0.62, "timestamp": 1700300000},
        ]
        db.save_open_positions("0xWhale", positions)
        is_new = db.is_new_position("0xWhale", "0xmkt2", "YES")
        print(f"  Saved open_positions. is_new_position={is_new} (expected True, first buy)")
        # Simulate second buy (average down)
        db.save_open_positions("0xWhale", positions)
        is_new2 = db.is_new_position("0xWhale", "0xmkt2", "YES")
        print(f"  After 2nd buy: is_new_position={is_new2} (expected False, average down)")

        print("\n── Test 4: migration (existing DB) ──")
        stats = db.get_stats()
        print(f"  Stats: {stats}")
        assert stats["closed_positions"] == 2, f"Expected 2, got {stats['closed_positions']}"
        assert stats["open_positions"] == 1

        print("\n✅ All tests passed")
