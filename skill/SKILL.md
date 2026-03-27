---
name: polymarket-2agent-copytrade
description: >
  Skill hướng dẫn vận hành hệ thống Polymarket Copy Trade Bot gồm 2 agent độc lập.
  Agent 1 (Whale Hunter) phát hiện whale wallet qua REST polling, phân tích lịch sử,
  scoring và cập nhật danh sách mỗi 1 giờ. Agent 2 (Copy Trader) thực thi copy trade
  theo 2 chế độ: AUTO (từ Agent 1) và MANUAL (ví chỉ định tay).
  criterion.md → AI tự viết filter_rules.py.
version: "3.0"
language: python
platform: linux-vps
---

# Polymarket 2-Agent Copy Trade Bot — Master Guide

---

## 1. Kiến trúc tổng quan

```
┌─────────────────────────────────────────────────────────────────┐
│                     AGENT 1 — Whale Hunter                      │
│                    (chạy liên tục, độc lập)                     │
│                                                                 │
│  [S1] REST Poll — data-api.polymarket.com/trades                │
│       └─ phát hiện trade > MIN_DETECT_SIZE (default $100)       │
│       └─ dedup bằng transaction_hash (tránh xử lý 2 lần)       │
│            │                                                    │
│  [S2] History Analyzer — fetch HISTORY_BATCH ví song song       │
│       └─ GET /trades?user=ADDR        → timing, volume, bot     │
│       └─ GET /closed-positions?user=  → win/loss/kelly          │
│            │                                                    │
│  [S3] Wallet Scorer — dùng filter_rules.py (AI-generated)       │
│       └─ evaluate(stats) → pass/fail + lý do                   │
│       └─ score(stats)    → điểm 0.0–1.0                        │
│            │                                                    │
│  [S4] Realtime Tracker — poll mỗi TRACKING_INTERVAL giây       │
│       └─ whale mới vào lệnh → ghi vào copy_queue.jsonl         │
│                                                                 │
│  [REPORT] Mỗi REPORT_INTERVAL_HOURS:                           │
│       └─ criterion_compiler → compile filter_rules.py           │
│       └─ xuất whale_report_YYYY-MM-DD_HH.md                    │
│       └─ cập nhật ## Active Wallets trong wallet.md            │
└──────────────────────────┬──────────────────────────────────────┘
                           │  2 file giao tiếp
          ┌────────────────┴──────────────────┐
          │  copy_queue.jsonl                 │  ← A1 append, A2 reads
          │  wallet.md (## Active Wallets)    │  ← A1 writes, A2 reads
          └────────────────┬──────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                     AGENT 2 — Copy Trader                       │
│                    (chạy liên tục, độc lập)                     │
│                                                                 │
│  [CONFIG WATCHER] reload wallet.md mỗi 15 giây                  │
│                                                                 │
│  [AUTO mode]  AUTO_COPY=on                                      │
│       └─ đọc copy_queue.jsonl từ byte cursor                   │
│       └─ chỉ copy ví trong ## Active Wallets                   │
│                                                                 │
│  [MANUAL mode] MANUAL_COPY=on                                   │
│       └─ poll trực tiếp từng ví trong ## Manual Wallets        │
│       └─ hoàn toàn độc lập với Agent 1                         │
│                                                                 │
│  [EXECUTOR] dùng chung cho cả 2 mode:                          │
│       └─ EIP-712 sign (Polygon off-chain signature)            │
│       └─ POST /order lên CLOB API                              │
│       └─ stop loss monitor mỗi 30 giây                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Hệ thống AI Compiler

Bạn viết tiêu chí lọc bằng ngôn ngữ tự nhiên → AI tự viết code Python.

```
criterion.md (tiếng Việt/Anh)
     │
     ▼  criterion_compiler.py
     │  1. Tính MD5 hash → so với hash cũ
     │  2. Nếu đổi → gọi AI API
     │  3. AI trả về Python code
     │  4. Validate: syntax + interface + dry-run
     │  5. OK → lưu filter_rules.py
     │     FAIL → rollback về bản cũ
     ▼
filter_rules.py (auto-generated)
     │  evaluate(stats) → (bool, reason)
     │  score(stats)    → float 0-1
     │  describe()      → dict thresholds
     ▼
agent1_whale_hunter.py → score_wallet() gọi filter_rules
```

### Interface bắt buộc của filter_rules.py

```python
def evaluate(stats: dict) -> tuple[bool, str]:
    """
    Kiểm tra ví có đủ điều kiện không.
    True, ""         → đạt, tiếp tục chấm điểm
    False, "lý do"   → loại, ví dụ: "low_wr:45.2%", "BOT:latency_sniper"
    """

def score(stats: dict) -> float:
    """Điểm 0.0–1.0. Cao hơn = tốt hơn. Chỉ gọi khi evaluate()=True."""

def describe() -> dict:
    """Trả về dict thresholds. Ví dụ: {"min_win_rate": 60, "min_kelly": 0.05}"""
```

### stats dict — input cho filter_rules

```python
{
    # Hiệu suất
    "win_rate": float,          # 0–100 (%)
    "total_trades": int,
    "total_closed": int,        # số markets đã resolve
    "wins": int, "losses": int,
    "net_pnl": float,           # lời/lỗ thuần (USDC)
    "total_volume": float,      # tổng USDC đã trade
    "avg_size": float,          # USDC trung bình/trade
    "trades_per_month": float,
    "account_age_days": int,
    "market_count": int,

    # Kelly: f* = (p*b - q) / b
    # p=win_rate/100, b=avg_win/avg_loss
    "kelly": float,             # > 0 = có edge thật
    "kelly_b": float,           # avg_win / avg_loss

    # Bot flags (đã tính sẵn)
    "bot_flag": bool,           # OR của tất cả bot_* bên dưới
    "bot_round": bool,          # >90% trades = bội số $100
    "bot_interval": bool,       # khoảng cách đều đặn (CV < 10%)
    "bot_hf": bool,             # >100 trades/tháng
    "bot_latency_sniper": bool, # >70% trades trong 3 giờ cố định
    "bot_micro": bool,          # avg_size < $5 VÀ >200 trades/tháng

    "suspicious_flag": bool,
    "suspicious_reason": str,
    "category_diversity": int,  # thường = 0 (API thiếu data)
}
```

---

## 3. File cấu hình

| File | Ai sửa | Hiệu lực | Mục đích |
|------|--------|----------|----------|
| `criterion.md` | Bạn | ~1h (hoặc `--force`) | Tiêu chí lọc whale |
| `wallet.md` | Bạn | 15 giây | Bật/tắt mode, ví manual, risk |
| `.env` | Bạn (1 lần) | Restart | API keys, thresholds hệ thống |
| `filter_rules.py` | AI tự tạo | Immediate | Code filter (đừng sửa tay) |

---

## 4. Cheat sheet — không cần restart

| Muốn làm gì | Sửa |
|------------|-----|
| Thêm/sửa tiêu chí lọc whale | `criterion.md` |
| Bật/tắt AUTO/MANUAL copy | `wallet.md` → `AUTO_COPY=` / `MANUAL_COPY=` |
| Thêm ví copy tay | `wallet.md` → `## Manual Wallets` |
| Đổi budget/stop loss | `wallet.md` → `MAX_TOTAL_BUDGET=` / `STOP_LOSS_PCT=` |

---

## 5. Công thức scoring mặc định

```
Kelly:  f* = max(0, (p*b - q) / b)
        p = win_rate/100, b = avg_win/avg_loss, q = 1-p

Score:  win_rate_component  * 0.30  (win rate vượt ngưỡng)
      + kelly_component      * 0.35  (Kelly fraction)
      + volume_component     * 0.15  (độ sâu vốn)
      + diversity_component  * 0.10  (đa dạng category)
      + age_component        * 0.10  (độ tin cậy)
```

---

## 6. Copy Queue format

```json
{
  "task_id": "1700000000000_0xabc123",
  "created_at": 1700000000,
  "wallet": "0xabc...",
  "wallet_score": 0.84,
  "wallet_win_rate": 72.3,
  "market": "0xdef...",
  "question": "Will Bitcoin exceed $100k?",
  "outcome": "YES",
  "price": 0.65,
  "whale_size_usdc": 24500.0,
  "token_id": "12345...",
  "source": "agent1_track"
}
```

---

## 7. CLI Reference

```bash
# Agent 1
python agent1_whale_hunter/agent1_whale_hunter.py              # chạy vĩnh viễn
python agent1_whale_hunter/agent1_whale_hunter.py --bootstrap  # khởi tạo DB
python agent1_whale_hunter/agent1_whale_hunter.py --status     # xem stats
python agent1_whale_hunter/agent1_whale_hunter.py --report     # force report

# Agent 2
python agent2_copy_trader/agent2_copy_trader.py                # chạy theo wallet.md
python agent2_copy_trader/agent2_copy_trader.py --auto         # force AUTO on
python agent2_copy_trader/agent2_copy_trader.py --manual       # force MANUAL on
python agent2_copy_trader/agent2_copy_trader.py --status       # xem stats

# AI Compiler
python agent1_whale_hunter/criterion_compiler.py               # compile if changed
python agent1_whale_hunter/criterion_compiler.py --force       # compile bắt buộc
python agent1_whale_hunter/criterion_compiler.py --watch       # auto-watch
```

---

Xem chi tiết: [AGENT1.md](AGENT1.md) · [AGENT2.md](AGENT2.md) · [API_REFERENCE.md](API_REFERENCE.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
