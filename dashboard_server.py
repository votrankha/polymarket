"""
dashboard_server.py — Flask API server cho Dashboard
═══════════════════════════════════════════════════════
Chạy:  python dashboard_server.py
Mở:   http://localhost:5000

Tại sao cần server thay vì đọc file trực tiếp?
  polybot.db = 186MB → browser không load nổi toàn bộ vào RAM
  Server query SQLite trực tiếp → chỉ trả data cần thiết
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from flask import Flask, jsonify, request, send_file

ROOT   = Path(__file__).parent
DB_PATH = ROOT / "shared" / "db" / "polybot.db"

app = Flask(__name__)

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def rows(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]

def one(conn, sql, params=()):
    cur = conn.execute(sql, params)
    r = cur.fetchone()
    return dict(r) if r else {}

# ── Dashboard HTML ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_file(ROOT / "dashboard.html")

# ── Stats tổng quan ────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    whale_count  = one(conn, "SELECT COUNT(DISTINCT address) as c FROM wallet_snapshots")["c"]
    trade_count  = one(conn, "SELECT COUNT(*) as c FROM whale_trades")["c"]
    total_vol    = one(conn, "SELECT COALESCE(SUM(usdc_size),0) as s FROM whale_trades")["s"]
    copy_count   = one(conn, "SELECT COUNT(*) as c FROM copy_trades")["c"]
    won          = one(conn, "SELECT COUNT(*) as c FROM copy_trades WHERE status='won'")["c"]
    lost_        = one(conn, "SELECT COUNT(*) as c FROM copy_trades WHERE status='lost'")["c"]
    pnl          = one(conn, "SELECT COALESCE(SUM(pnl_usdc),0) as s FROM copy_trades")["s"]
    spent        = one(conn, "SELECT COALESCE(SUM(usdc_spent),0) as s FROM copy_trades")["s"]
    top_score    = one(conn, "SELECT MAX(score) as s FROM wallet_snapshots")["s"] or 0
    market_count = one(conn, "SELECT COUNT(*) as c FROM markets")["c"]
    db_mb        = round(DB_PATH.stat().st_size / 1024 / 1024, 1)
    wr = round(won/(won+lost_)*100, 1) if (won+lost_) > 0 else None
    conn.close()
    return jsonify({
        "whales": whale_count, "trades": trade_count,
        "total_volume": round(total_vol, 2),
        "copies": copy_count, "won": won, "lost": lost_,
        "win_rate": wr, "total_pnl": round(pnl, 2),
        "usdc_spent": round(spent, 2), "top_score": round(top_score, 4),
        "markets": market_count, "db_mb": db_mb,
    })

# ── Whale wallets ──────────────────────────────────────────────
@app.route("/api/whales")
def api_whales():
    sort  = request.args.get("sort", "score")
    valid = {"score","win_rate","kelly","net_pnl","total_volume","avg_size"}
    sort  = sort if sort in valid else "score"
    search = request.args.get("q", "").lower()
    limit  = min(int(request.args.get("limit", 200)), 1000)

    conn = get_conn()
    sql = f"""
        SELECT ws.*,
          (SELECT COUNT(*) FROM whale_trades wt WHERE wt.address=ws.address) as trade_count
        FROM wallet_snapshots ws
        WHERE ws.id IN (SELECT MAX(id) FROM wallet_snapshots GROUP BY address)
        {"AND LOWER(ws.address) LIKE ?" if search else ""}
        ORDER BY ws.{sort} DESC
        LIMIT {limit}
    """
    params = (f"%{search}%",) if search else ()
    data = rows(conn, sql, params)
    conn.close()
    return jsonify(data)

# ── Wallet detail + snapshot history ──────────────────────────
@app.route("/api/wallet/<address>")
def api_wallet(address):
    conn = get_conn()
    snapshots = rows(conn,
        "SELECT ts, score, win_rate, kelly, net_pnl FROM wallet_snapshots WHERE address=? ORDER BY ts ASC",
        (address.lower(),))
    trade_count = one(conn, "SELECT COUNT(*) as c FROM whale_trades WHERE address=?", (address.lower(),))["c"]
    copy_count  = one(conn, "SELECT COUNT(*) as c FROM copy_trades WHERE wallet=?",  (address.lower(),))["c"]
    conn.close()
    return jsonify({"snapshots": snapshots, "trade_count": trade_count, "copy_count": copy_count})

# ── Trades ─────────────────────────────────────────────────────
@app.route("/api/trades")
def api_trades():
    offset  = int(request.args.get("offset", 0))
    limit   = min(int(request.args.get("limit", 100)), 500)
    search  = request.args.get("q", "").lower()
    source  = request.args.get("source", "")
    outcome = request.args.get("outcome", "")

    where = []
    params = []
    if search:
        where.append("(LOWER(address) LIKE ? OR LOWER(question) LIKE ? OR LOWER(market_id) LIKE ?)")
        params += [f"%{search}%"]*3
    if source:
        where.append("source=?"); params.append(source)
    if outcome:
        where.append("outcome=?"); params.append(outcome)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    data = rows(conn, f"SELECT * FROM whale_trades {where_sql} ORDER BY ts DESC LIMIT {limit} OFFSET {offset}", params)
    total = one(conn, f"SELECT COUNT(*) as c FROM whale_trades {where_sql}", params)["c"]
    conn.close()
    return jsonify({"data": data, "total": total, "offset": offset})

# ── Copy trades ────────────────────────────────────────────────
@app.route("/api/copies")
def api_copies():
    status = request.args.get("status", "")
    search = request.args.get("q", "").lower()
    where  = []
    params = []
    if status: where.append("status=?"); params.append(status)
    if search:
        where.append("(LOWER(wallet) LIKE ? OR LOWER(question) LIKE ?)")
        params += [f"%{search}%"]*2
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    conn  = get_conn()
    data  = rows(conn, f"SELECT * FROM copy_trades {where_sql} ORDER BY copied_at DESC", params)
    conn.close()
    return jsonify(data)

# ── Markets ────────────────────────────────────────────────────
@app.route("/api/markets")
def api_markets():
    resolved = request.args.get("resolved", "")
    search   = request.args.get("q", "").lower()
    where    = []
    params   = []
    if resolved != "": where.append("resolved=?"); params.append(int(resolved))
    if search:
        where.append("(LOWER(question) LIKE ? OR LOWER(condition_id) LIKE ?)")
        params += [f"%{search}%"]*2
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    data = rows(conn, f"SELECT * FROM markets {where_sql} ORDER BY cached_at DESC LIMIT 500", params)
    conn.close()
    return jsonify(data)

# ── Top markets by whale activity ─────────────────────────────
@app.route("/api/top-markets")
def api_top_markets():
    conn = get_conn()
    data = rows(conn, """
        SELECT market_id, question,
               COUNT(*) as whale_count,
               SUM(usdc_size) as total_volume,
               AVG(price) as avg_price
        FROM whale_trades
        WHERE market_id != ''
        GROUP BY market_id
        ORDER BY whale_count DESC
        LIMIT 20
    """)
    conn.close()
    return jsonify(data)

# ── Closed positions per wallet ───────────────────────────────────────────
@app.route("/api/closed-positions/<address>")
def api_closed_positions(address):
    """PnL từng market đã resolve của 1 ví."""
    conn = get_conn()
    data = rows(conn, """
        SELECT cp.*, m.category, m.end_date
        FROM closed_positions cp
        LEFT JOIN markets m ON cp.market_id = m.condition_id
        WHERE cp.address = ?
        ORDER BY cp.resolved_at DESC
        LIMIT 500
    """, (address.lower(),))
    conn.close()
    return jsonify(data)

# ── Open positions per wallet ─────────────────────────────────────────────
@app.route("/api/open-positions/<address>")
def api_open_positions(address):
    """Vị thế đang mở + unrealized PnL của 1 ví."""
    conn = get_conn()
    data = rows(conn, """
        SELECT op.*, m.end_date, m.current_price_yes,
               m.resolved, m.winning_outcome
        FROM open_positions op
        LEFT JOIN markets m ON op.market_id = m.condition_id
        WHERE op.address = ?
        ORDER BY op.invested DESC
    """, (address.lower(),))
    conn.close()
    return jsonify(data)

# ── Trade history enriched với PnL ──────────────────────────────────────
@app.route("/api/trades-enriched")
def api_trades_enriched():
    """
    Trade history JOIN với closed_positions để lấy PnL từng lệnh.
    Đây là endpoint chính cho tab Trade History trong dashboard.
    """
    offset  = int(request.args.get("offset", 0))
    limit   = min(int(request.args.get("limit", 100)), 500)
    search  = request.args.get("q", "").lower()
    source  = request.args.get("source", "")
    outcome = request.args.get("outcome", "")
    result  = request.args.get("result", "")   # won | lost | open | sold

    where  = []
    params = []
    if search:
        where.append("(LOWER(wt.address) LIKE ? OR LOWER(wt.question) LIKE ?)")
        params += [f"%{search}%"] * 2
    if source:
        where.append("wt.source=?");  params.append(source)
    if outcome:
        where.append("wt.outcome=?"); params.append(outcome)
    if result:
        where.append("cp.result=?");  params.append(result)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    data = rows(conn, f"""
        SELECT
            wt.tx_hash, wt.address, wt.market_id, wt.question,
            wt.outcome, wt.price, wt.usdc_size, wt.shares, wt.ts, wt.source,
            cp.realized_pnl, cp.invested as cp_invested,
            cp.end_price, cp.result, cp.resolved_at,
            CASE
                WHEN cp.realized_pnl IS NOT NULL AND cp.invested > 0
                THEN ROUND(cp.realized_pnl / cp.invested * 100, 1)
                ELSE NULL
            END as roi_pct,
            op.current_price, op.unrealized_pnl, op.trade_count
        FROM whale_trades wt
        LEFT JOIN closed_positions cp
            ON wt.address = cp.address AND wt.market_id = cp.market_id
        LEFT JOIN open_positions op
            ON wt.address = op.address AND wt.market_id = op.market_id
        {where_sql}
        ORDER BY wt.ts DESC
        LIMIT {limit} OFFSET {offset}
    """, params)

    total = one(conn, f"""
        SELECT COUNT(*) as c FROM whale_trades wt
        LEFT JOIN closed_positions cp ON wt.address=cp.address AND wt.market_id=cp.market_id
        LEFT JOIN open_positions op   ON wt.address=op.address AND wt.market_id=op.market_id
        {where_sql}
    """, params)["c"]

    # Stats tổng hợp
    stats = one(conn, """
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN cp.result='won'  THEN 1 ELSE 0 END) as won,
            SUM(CASE WHEN cp.result='lost' THEN 1 ELSE 0 END) as lost,
            ROUND(SUM(COALESCE(cp.realized_pnl, 0)), 2) as total_pnl,
            ROUND(SUM(wt.usdc_size), 2) as total_volume
        FROM whale_trades wt
        LEFT JOIN closed_positions cp ON wt.address=cp.address AND wt.market_id=cp.market_id
    """)

    conn.close()
    return jsonify({"data": data, "total": total, "offset": offset, "stats": stats})

# ── Summary per wallet: closed PnL ────────────────────────────────────────
@app.route("/api/pnl-summary/<address>")
def api_pnl_summary(address):
    conn = get_conn()
    summary = one(conn, """
        SELECT
            COUNT(*) as total_markets,
            SUM(CASE WHEN result='won'  THEN 1 ELSE 0 END) as won,
            SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) as lost,
            SUM(CASE WHEN result='sold' THEN 1 ELSE 0 END) as sold,
            ROUND(SUM(realized_pnl), 2) as total_pnl,
            ROUND(SUM(invested), 2) as total_invested,
            ROUND(AVG(CASE WHEN result='won'  THEN realized_pnl END), 2) as avg_win,
            ROUND(AVG(CASE WHEN result='lost' THEN realized_pnl END), 2) as avg_loss,
            ROUND(MAX(realized_pnl), 2) as best_trade,
            ROUND(MIN(realized_pnl), 2) as worst_trade
        FROM closed_positions
        WHERE address = ?
    """, (address.lower(),))

    open_summary = one(conn, """
        SELECT
            COUNT(*) as open_count,
            ROUND(SUM(invested), 2) as open_invested,
            ROUND(SUM(unrealized_pnl), 2) as total_unrealized
        FROM open_positions WHERE address = ?
    """, (address.lower(),))

    conn.close()
    return jsonify({**summary, **open_summary})


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"❌ Database không tìm thấy: {DB_PATH}")
        print("   Chạy agent1 trước để tạo database")
        sys.exit(1)
    try:
        from flask import Flask
    except ImportError:
        print("❌ Flask chưa cài: pip install flask")
        sys.exit(1)
    print(f"✅ Database: {DB_PATH} ({DB_PATH.stat().st_size//1024//1024}MB)")
    print(f"🌐 Dashboard: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
