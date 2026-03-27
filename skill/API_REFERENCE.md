# API_REFERENCE.md — Polymarket API Reference

## Base URLs

| Service | URL | Dùng để |
|---------|-----|---------|
| Gamma API | `https://gamma-api.polymarket.com` | Market data, leaderboard |
| CLOB API | `https://clob.polymarket.com` | Đặt/hủy lệnh, orderbook |
| Data API | `https://data-api.polymarket.com` | Trade history, wallet activity |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Orderbook snapshots (không dùng cho trade detection) |

---

## Data API (Endpoint chính của bot)

### GET /trades — Lịch sử trade của 1 ví

```
GET https://data-api.polymarket.com/trades?user=0xADDRESS&limit=500
```

Params:
- `user` = địa chỉ ví (bắt buộc khi lấy lịch sử 1 ví)
- `limit` = số records (tối đa 500)
- `offset` = phân trang

### GET /trades — Trade stream toàn market (S1 polling)

```
GET https://data-api.polymarket.com/trades?filterType=CASH&filterAmount=100
```

Params:
- `filterType=CASH` = lọc theo USDC size
- `filterAmount=N` = chỉ lấy trade >= N USDC

Response trade object:
```json
{
  "id": "0xhash...",
  "transactionHash": "0xtxhash...",   // dùng để dedup ở S1
  "market": "0xconditionId...",
  "outcome": "Yes",
  "side": "BUY",
  "price": "0.65",
  "usdcSize": "15000.00",
  "size": "23076.92",                  // số shares
  "makerAddress": "0xwallet...",       // địa chỉ whale
  "timestamp": "1700000000",
  "createdAt": "1700000000"
}
```

---

### GET /closed-positions — Vị thế đã đóng của 1 ví

```
GET https://data-api.polymarket.com/closed-positions?user=0xADDRESS&limit=500
```

**Tại sao quan trọng?**
Polymarket resolve positions tự động — không có transaction SELL.
Endpoint này là nguồn duy nhất có `realizedPnl` chính xác.

Response:
```json
[
  {
    "conditionId": "0xmarket...",
    "title": "Will X happen?",
    "outcome": "Yes",
    "realizedPnl": 250.50,     // DƯƠNG = thắng, ÂM = thua
    "settledAt": 1700000000
  }
]
```

---

## Gamma API

### GET /leaderboard

```
GET https://gamma-api.polymarket.com/leaderboard?limit=300
```

Response:
```json
[
  {
    "address": "0xabc...",
    "proxyWallet": "0xproxy...",
    "pnl": 184230.5,
    "volume": 2100000.0
  }
]
```

> ⚠️ Lấy top 150 ví từ đây để seed DB lúc bootstrap.

---

### GET /markets/{condition_id}

```
GET https://gamma-api.polymarket.com/markets/0xCONDITION_ID
```

Response:
```json
{
  "conditionId": "0x...",
  "question": "Will X happen?",
  "endDate": "2025-12-31",
  "active": true,
  "tokens": [
    {"tokenId": "111...", "outcome": "Yes", "price": 0.65},
    {"tokenId": "222...", "outcome": "No",  "price": 0.35}
  ]
}
```

---

## CLOB API

### POST /order — Đặt lệnh

```
POST https://clob.polymarket.com/order
Authorization: (EIP-712 signed)
```

Request body:
```json
{
  "order": {
    "salt": 12345,
    "maker": "0xYOUR_WALLET",
    "signer": "0xYOUR_WALLET",
    "taker": "0x0000000000000000000000000000000000000000",
    "tokenId": "TOKEN_ID",
    "makerAmount": "50000000",   // USDC với 6 decimals (50 USDC = 50000000)
    "takerAmount": "76923076",   // shares với 6 decimals
    "expiration": 1700003600,
    "nonce": 0,
    "feeRateBps": 0,
    "side": "BUY",               // BUY hoặc SELL
    "signatureType": 0
  },
  "signature": "0xSIGNATURE...",
  "orderType": "GTC"             // Good Till Cancelled
}
```

Response:
```json
{
  "orderID": "0xORDER_HASH...",
  "status": "matched"            // "matched", "delayed", "unmatched"
}
```

> ⚠️ Nếu response không có `orderID` → lệnh thất bại, check `error` field.

---

### GET /data/price — Giá hiện tại

```
GET https://clob.polymarket.com/data/price?token_id=TOKEN_ID&side=BUY
```

Response:
```json
{
  "price": "0.6503"
}
```

---

## Rate Limits (ước tính)

| API | Rate limit |
|-----|-----------|
| Data API `/trades` | ~60 req/min per IP |
| Gamma API | ~30 req/min per IP |
| CLOB API | ~100 req/min per account |

**Khi bị 429:** Tăng `TRACKING_INTERVAL`, `POLL_INTERVAL`, giảm `HISTORY_BATCH`.

---

## Xử lý response không nhất quán

Gamma API đôi khi trả về format khác nhau. Client code xử lý cả 2:

```python
# /activity có thể trả về {"data": [...]} hoặc trực tiếp [...]
raw = await response.json()
if isinstance(raw, dict):
    items = raw.get("data", raw.get("trades", []))
else:
    items = raw  # trực tiếp là list
```

---

## Polygon / EIP-712 Constants

```python
CHAIN_ID = 137                  # Polygon Mainnet
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # CTF Exchange
COLLATERAL_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon
CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
```
