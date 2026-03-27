# AGENT2.md — Copy Trader Chi Tiết

## Mục đích

Agent 2 thực thi copy trade. Chạy **hoàn toàn độc lập** với Agent 1 —
có thể bật/tắt bất kỳ lúc nào mà không ảnh hưởng lẫn nhau.

---

## Hai chế độ copy trade

### Mode A — AUTO (từ Agent 1)

```
copy_queue.jsonl
      │  byte-cursor read (không đọc lại cũ, không bỏ mới)
      ▼
Lọc: chỉ copy ví trong ## Active Wallets (wallet.md)
      │
      ▼
EIP-712 sign → CLOB submit
```

**Tại sao cần check Active Wallets?**
Agent 1 có thể xóa ví khỏi Active Wallets khi ví xuống điểm.
Nếu không check, Agent 2 vẫn copy ví đã "bị loại" → rủi ro.

**Bật:** `AUTO_COPY=on` trong wallet.md
**Tắt:** `AUTO_COPY=off` — queue vẫn tích lại, sẽ đọc khi bật lại
**Override CLI:** `python agent2_copy_trader.py --auto`

---

### Mode B — MANUAL (ví chỉ định tay)

```
## Manual Wallets trong wallet.md
      │
      │  poll trực tiếp mỗi SCAN_INTERVAL_SECONDS
      ▼
GET /trades?user=ADDR&limit=20
      │  filter: timestamp > last_polled AND side=BUY
      ▼
EIP-712 sign → CLOB submit
```

**Dùng khi:**
- Agent 1 chưa phát hiện ví bạn muốn copy
- Bạn muốn copy ví cụ thể không cần qua tiêu chí scoring
- Test bot với 1 ví cụ thể

**Bật:** `MANUAL_COPY=on`
**Polling:** Mỗi ví poll tuần tự với delay 0.3s giữa các ví (tránh rate limit)

---

## wallet.md — Cấu hình đầy đủ

```markdown
## Settings

AUTO_COPY=on           # copy theo Agent 1 (on/off)
MANUAL_COPY=on         # copy ví chỉ định tay (on/off)
MAX_TOTAL_BUDGET=500   # Tổng USDC bot được phép dùng (0 = không giới hạn)
MAX_PER_MARKET=100     # Tối đa USDC cho 1 lệnh (0 = không giới hạn)
STOP_LOSS_PCT=30       # Dừng copy ví nếu lỗ 30% từ khi bắt đầu copy
MAX_OPEN_POSITIONS=10  # Không mở quá N vị thế cùng lúc
MIN_SPREAD=0.05        # Không copy nếu giá > 0.95 (quá gần kết quả, không còn upside)
SCAN_INTERVAL_SECONDS=30  # Tần suất poll Manual Wallets


## Manual Wallets
# Cú pháp: địa_chỉ | budget_USDC | category_filter | ghi_chú
# budget_USDC = USDC tối đa dùng để copy ví này
# category_filter = "all" hoặc "crypto", "geopolitics", "sports"

0xWHALE_ADDRESS_1 | 75  | crypto | Whale chuyên crypto
0xWHALE_ADDRESS_2 | 50  | all    | Whale đa dạng
0xWHALE_ADDRESS_3 | 100 | geo    | Whale geopolitics


## Blacklist
# Địa chỉ trong đây sẽ bị bỏ qua hoàn toàn (cả AUTO và MANUAL)
0xBAD_WALLET_1 | spam bot
0xBAD_WALLET_2 | suspected insider


## Active Wallets
# Phần này do Agent 1 tự ghi — ĐỪNG sửa tay
# Format: địa_chỉ | budget | filter | metadata
0xabc... | 50 | all | score=0.84 kelly=0.21 wr=72.3%
0xdef... | 25 | all | score=0.74 kelly=0.08 wr=63.1%
```

---

## EIP-712 Order Signing

Polymarket dùng EIP-712 standard (Ethereum typed structured data signing)
để ký lệnh off-chain trên Polygon network.

**Tại sao off-chain?**
- Không tốn gas mỗi lệnh
- Lệnh được submit lên CLOB (Central Limit Order Book) của Polymarket
- CLOB match lệnh, chỉ settle on-chain khi cần thiết

**Luồng ký lệnh:**
```python
# 1. Tạo order struct
order = {
    "maker": WALLET_ADDRESS,
    "tokenId": token_id,           # từ copy task
    "makerAmount": usdc_amount,    # USDC bạn trả
    "takerAmount": shares_amount,  # shares bạn nhận
    "side": "BUY",
    "expiration": int(time.time()) + 3600,  # hết hạn sau 1 giờ
    "nonce": random_nonce,
}

# 2. EIP-712 structured data hash
domain = {
    "name": "Polymarket CTF Exchange",
    "version": "1",
    "chainId": 137,  # Polygon Mainnet
    "verifyingContract": EXCHANGE_ADDRESS,
}
signature = account.sign_typed_data(domain, types, order)

# 3. Submit lên CLOB
POST https://clob.polymarket.com/order
{
    "order": order,
    "signature": signature.signature.hex(),
    "orderType": "GTC"  # Good Till Cancelled
}
```

---

## Stop Loss Monitor

Chạy ngầm mỗi 30 giây:

```python
for position in open_positions:
    current_price = get_current_price(position.token_id)
    pnl_pct = (current_price - position.entry_price) / position.entry_price * 100
    if pnl_pct < -STOP_LOSS_PCT:
        # Bán hết vị thế → đặt lệnh SELL
        close_position(position)
        log(f"STOP LOSS: {position.market} pnl={pnl_pct:.1f}%")
```

---

## Byte Cursor — tại sao không dùng line number?

**Vấn đề với line number:** Nếu Agent 2 restart giữa chừng, không biết đọc từ dòng nào.

**Giải pháp byte cursor:**
```python
# Đọc
cursor = int(Path(".queue_cursor").read_text() or "0")
with open("copy_queue.jsonl", "rb") as f:
    f.seek(cursor)                    # nhảy thẳng đến vị trí đã đọc
    new_tasks = f.readlines()         # đọc từ đó đến EOF
    new_cursor = f.tell()             # ghi nhớ vị trí hiện tại

# Lưu
Path(".queue_cursor").write_text(str(new_cursor))
```

**Ưu điểm:**
- Restart → tiếp tục đúng chỗ
- Queue chỉ append → không bao giờ corrupt
- Không đọc lại task cũ, không bỏ lỡ task mới

---

## Volume tự động tính theo Kelly

| Trường hợp | USDC/trade |
|-----------|-----------|
| Ví có Kelly ≥ 0.15 (edge tốt) | $50 |
| Ví có Kelly < 0.15 (edge yếu) | $25 |
| Budget còn lại < $25 | Dừng copy ví này |

*Có thể override bằng `MAX_PER_MARKET` trong wallet.md*

---

## Log bình thường của Agent 2

```
[wallet.md] Reloaded — AUTO=ON  MANUAL=ON  auto_wallets=23  manual_wallets=2
[AUTO] 🔔 WHALE TRADE
   Wallet  : 0xba664f999a18dce0...
   Market  : Will Bitcoin exceed $100k by Dec 2026?
   Outcome : YES @ 0.6503  whale=$24,500
   Copying : $50.00 USDC
  ↳ ✓ ORDER PLACED  orderId=0xABC...
[MANUAL] Polling 0xWHALE... (2 wallets)
  → 0xWHALE: 1 new trade found
  ↳ ✓ ORDER PLACED  orderId=0xDEF...
[STOP LOSS] ⚠️ Closing position: pnl=-31.2%
```
