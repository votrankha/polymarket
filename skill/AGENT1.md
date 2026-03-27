# AGENT1.md — Whale Hunter Chi Tiết

## Mục đích

Agent 1 chạy **hoàn toàn độc lập** 24/7. Nhiệm vụ: tìm và theo dõi whale wallet
trên Polymarket, báo cho Agent 2 khi whale vào lệnh mới.

---

## Pipeline 4 giai đoạn

### [S1] REST Trade Scanner

**Tại sao dùng REST thay vì WebSocket?**

Polymarket có WebSocket (`wss://ws-subscriptions-clob.../ws/market`) nhưng chỉ
push orderbook snapshots, không push trade events đáng tin cậy. Sau khi test
500 assets × 120 giây → 0 trade events thật. REST poll ổn định hơn nhiều.

**Endpoint:**
```
GET https://data-api.polymarket.com/trades?filterType=CASH&filterAmount=N
```

- `filterType=CASH` → lọc theo USDC size
- `filterAmount=N` → chỉ lấy trade >= N USDC (= MIN_DETECT_SIZE trong .env)

**Deduplication:**
```python
seen_tx: set = set()    # lưu transaction_hash đã xử lý
MAX_SEEN = 5000         # giới hạn kích thước set để không rò rỉ memory

if tx_hash in seen_tx:
    continue            # bỏ qua trade đã xử lý
seen_tx.add(tx_hash)    # đánh dấu đã xử lý
```

**Khi phát hiện trade đủ lớn:**
- Địa chỉ chưa trong DB → thêm vào candidate queue (chờ S2 phân tích)
- Địa chỉ đã tracked → cập nhật `last_trade_ts`, S4 sẽ emit copy task

---

### [S2] History Analyzer

**Tại sao cần 2 API calls song song?**

Polymarket không có SELL transactions — vị thế tự động resolve khi market đóng.
Vì vậy không thể tính win/loss từ trade history. `/closed-positions` là nguồn
duy nhất có `realizedPnl` chính xác.

```python
# Fetch song song để giảm latency
trades, closed = await asyncio.gather(
    client.get_wallet_activity(addr),     # /trades?user=ADDR
    client.get_closed_positions(addr)     # /closed-positions?user=ADDR
)
```

**Từ `trades`** (dùng để tính):
- `account_age_days` = (now - first_trade_timestamp) / 86400
- `total_volume`, `avg_size`
- `trades_per_month` = total_trades / (age_days / 30)
- `all_sizes`, `all_ts` → dùng cho bot detection

**Từ `closed_positions`** (dùng để tính):
- `wins`, `losses`, `win_rate`
- `net_pnl` = sum(realizedPnl)
- `kelly` = max(0, (p*b - q) / b)

---

### [S3] Wallet Scorer

**Delegate hoàn toàn cho `filter_rules.py`:**

```python
def score_wallet(stats: dict, cfg: dict) -> tuple[float, str]:
    try:
        rules = load_filter_rules()       # load động, tự reload khi file đổi
        passed, reason = rules.evaluate(stats)
        if not passed:
            return 0.0, reason            # ví bị loại
        return round(float(rules.score(stats)), 4), ""
    except Exception as e:
        # Fallback hardcode nếu filter_rules bị lỗi
        ...
```

**Bot detection (tính trong `analyze_history`, trước khi vào filter_rules):**

| Flag | Điều kiện | Giải thích |
|------|-----------|-----------|
| `bot_round` | >90% trades = bội số $100 | Robot dùng round numbers cố định |
| `bot_interval` | CV khoảng cách < 10% | Cron job đặt lệnh theo giờ |
| `bot_hf` | >100 trades/tháng | High-frequency automated |
| `bot_latency_sniper` | >70% trades trong 3 giờ/ngày | Exploit lag 30-90s của crypto markets |
| `bot_micro` | avg_size < $5 VÀ >200/tháng | Wash trading / spam |

**Latency sniper — giải thích kỹ:**
```
Polymarket có 15-phút crypto markets. Giá trên Polymarket lag 30-90 giây
so với giá thực. Bot sniper vào lệnh ngay trước khi market expire để
capture delta chắc chắn — đây là algo trade, không thể copy bằng tay.
Dấu hiệu: >70% trades tập trung vào ≤3 giờ UTC cố định trong ngày.
```

---

### [S4] Realtime Tracker

Với mỗi ví đã được promote vào DB, S4 poll liên tục mỗi `TRACKING_INTERVAL` giây:

```
GET /trades?user=ADDR&limit=5
→ có trade mới (ts > last_trade_ts)?
   YES → tạo copy task → append vào copy_queue.jsonl
   NO  → bỏ qua
```

**Format copy task:** Xem `skill/SKILL.md` section 6.

---

## criterion_compiler integration

Mỗi lần report cycle:

```python
async def report_cycle():
    # 1. Compile filter_rules.py nếu criterion.md thay đổi
    compile_criterion()   # no-op nếu hash không đổi

    # 2. Log thresholds hiện tại
    rules = load_filter_rules()
    logger.info(f"Thresholds: {rules.describe()}")

    # 3. Xuất report ...
    # 4. Cập nhật wallet.md ...
```

---

## Cấu trúc DB (tracked_wallets.json)

```json
{
  "0xabc...": {
    "address": "0xabc...",
    "score": 0.84,
    "win_rate": 72.3,
    "kelly": 0.213,
    "avg_size": 7451.0,
    "account_age_days": 312,
    "total_closed": 47,
    "net_pnl": 18420.5,
    "promoted_at": 1700000000,
    "last_trade_ts": 1700100000,
    "source": "bootstrap"    // "bootstrap" hoặc "stream"
  }
}
```

---

## Output format báo cáo (whale_report_YYYY-MM-DD_HH.md)

```markdown
# Whale Report — 2025-01-15 14:00 UTC

## Summary
- Wallets tracked: 23
- New this cycle: 2
- Removed: 0

## Top Wallets

| Address | Score | WR | Kelly | Avg Size | Age |
|---------|-------|----|-------|----------|-----|
| 0xba664f... | 0.78 | 84.0% | 0.691 | $7,451 | 490d |
| 0x16f91d... | 0.73 | 90.9% | 0.878 | $639   | 494d |

## Discarded This Cycle

| Address | Reason |
|---------|--------|
| 0xabc... | BOT:latency_sniper |
| 0xdef... | low_wr:34.5% |
```

---

## ENV variables liên quan đến Agent 1

```env
MIN_DETECT_SIZE=100         # USDC threshold để detect trade ở S1
HISTORY_BATCH=6             # số ví fetch song song ở S2 (tăng = nhanh nhưng dễ rate limit)
TRACKING_INTERVAL=20        # giây giữa 2 lần poll S4
BOOTSTRAP_LIMIT=150         # số ví từ leaderboard để seed DB lần đầu
REPORT_INTERVAL_HOURS=1     # tần suất report + compile filter_rules
LOG_LEVEL=INFO              # INFO hoặc DEBUG (debug xem raw API response)
POLL_INTERVAL=10            # giây giữa 2 lần poll S1 (REST trade stream)
```
