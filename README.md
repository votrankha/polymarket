# 🐳 Polymarket 2-Agent Copy Trade Bot

> **Dành cho người mới bắt đầu:** Tài liệu này giải thích từng bước từ "không biết gì"
> đến "bot đang chạy trên VPS". Đọc từ trên xuống theo thứ tự.

---

## Polymarket là gì? Bot này làm gì?

**Polymarket** là sàn giao dịch dự đoán (prediction market) — người dùng mua/bán
"cổ phiếu" YES/NO cho các sự kiện thực tế (bầu cử, giá Bitcoin, kết quả thể thao...).
Ví dụ: "Bitcoin > $100k trước 2026?" — bạn mua YES với giá $0.65 → nếu đúng bạn nhận $1.00.

**Bot này làm 2 việc:**

1. **Agent 1 (Whale Hunter):** Tự động theo dõi những ví đang "thắng lớn" trên Polymarket
   (gọi là "whale" — cá voi). Khi phát hiện whale vào lệnh mới → ghi vào hàng đợi.

2. **Agent 2 (Copy Trader):** Đọc hàng đợi từ Agent 1 và tự động đặt lệnh tương tự
   vào tài khoản của bạn. Nguyên lý: "nếu người giỏi mua YES, mình cũng mua YES".

```
┌──────────────────────────────────────────────────────┐
│                AGENT 1 — Whale Hunter                │
│                                                      │
│  Poll REST API → phát hiện trade lớn (> $100)       │
│        ↓                                             │
│  Tải lịch sử ví → phân tích win rate, Kelly...      │
│        ↓                                             │
│  Chấm điểm ví (dựa theo criterion.md)               │
│        ↓                                             │
│  Ví đạt điểm → theo dõi realtime                    │
│        ↓                                             │
│  Whale vào lệnh mới → ghi vào copy_queue.jsonl      │
│                                                      │
│  ⏱ Mỗi 1 giờ: xuất báo cáo + cập nhật wallet.md   │
└──────────────────────────┬───────────────────────────┘
                           │  giao tiếp qua 2 file:
                           │  • copy_queue.jsonl  (lệnh copy)
                           │  • wallet.md         (danh sách ví tốt)
┌──────────────────────────▼───────────────────────────┐
│                AGENT 2 — Copy Trader                 │
│                                                      │
│  [AUTO]   đọc copy_queue.jsonl → đặt lệnh           │
│  [MANUAL] poll ví bạn chỉ định tay → đặt lệnh       │
│                                                      │
│  Ký lệnh EIP-712 → gửi lên Polymarket CLOB          │
└──────────────────────────────────────────────────────┘
```

---

## Kiến trúc tự học — AI tự viết code filter

**Tính năng đặc biệt:** Bạn không cần biết code để thay đổi tiêu chí lọc whale.
Chỉ cần viết bằng **tiếng Việt** trong `criterion.md` — AI agent đọc hiểu và tự
viết lại code Python tương ứng vào `filter_rules.py`.

```
criterion.md  ← bạn chỉ sửa file này (tiếng Việt/Anh đều được)
     │
     ▼  criterion_compiler.py đọc, gọi AI API
filter_rules.py  ← AI tự viết, chứa hàm evaluate() và score()
     │
     ▼
agent1_whale_hunter.py  ← dùng filter_rules để lọc ví
```

**Cơ chế:**
- `criterion_compiler.py` kiểm tra hash của `criterion.md`
- Nếu file thay đổi → gọi AI API → AI viết lại `filter_rules.py`
- Validate code trước khi lưu — nếu AI viết sai → tự rollback về bản cũ
- Agent 1 reload mỗi 1 giờ, hoặc force compile ngay bằng `--force`

---

## Yêu cầu hệ thống

| Thứ | Tối thiểu | Khuyến nghị |
|-----|-----------|-------------|
| VPS | 1 vCPU, 1 GB RAM | 2 vCPU, 2 GB RAM |
| OS | Ubuntu 20.04 | Ubuntu 22.04 LTS |
| Python | 3.10 | 3.11+ |
| Disk | 2 GB | 5 GB |
| USDC | $25 (minimum/trade) | $100–500 |
| MATIC | 1 MATIC (gas) | 2 MATIC |

> **MATIC** là token gas của mạng Polygon — dùng để trả phí giao dịch blockchain.
> Rất rẻ (~$0.5–1 cho vài trăm lệnh). Mua trên Binance/Coinbase rồi rút về ví.

---

## Cài đặt từng bước

### Bước 1 — Tạo Polymarket Proxy Wallet

Polymarket dùng "proxy wallet" (ví phụ trên L2/Polygon) tách biệt với ví MetaMask gốc.
Bot cần private key của proxy wallet để ký lệnh tự động.

```
1. Vào polymarket.com → đăng nhập MetaMask
2. Settings → Wallets → "Create trading wallet" → xác nhận
3. LƯU NGAY private key (chỉ hiển thị 1 lần duy nhất!)
   Format: 64 ký tự hex, KHÔNG có "0x" ở đầu
   Ví dụ: a1b2c3d4e5f6a1b2c3d4e5f6... (64 ký tự)
4. Ghi nhớ địa chỉ ví proxy (0x...)
```

> ⚠️ Private key = quyền kiểm soát tiền. KHÔNG chia sẻ với ai.

### Bước 2 — Tạo API Keys

```
1. polymarket.com → Settings → API Keys → "Create New Key"
2. Ký xác nhận bằng proxy wallet
3. Lưu lại: API Key + Secret + Passphrase
```

### Bước 3 — Nạp tiền (mạng Polygon)

- **USDC**: tiền để trade (tối thiểu $25)
- **MATIC**: ~1-2 MATIC để trả gas (~$0.5)

> Rút từ sàn CEX về địa chỉ proxy wallet, chọn mạng **Polygon**. Không dùng Ethereum.

### Bước 4 — Cài đặt lên VPS

```bash
cd /opt/polymarket_2agent_bot
chmod +x setup.sh && bash setup.sh
```

### Bước 5 — Cấu hình

```bash
cp shared/.env.example shared/.env
nano shared/.env
# Điền: WALLET_ADDRESS, PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE
```

### Bước 6 — Khởi tạo database

```bash
source venv/bin/activate
python agent1_whale_hunter/agent1_whale_hunter.py --bootstrap
# Mất 3-5 phút, seed top 150 ví từ leaderboard Polymarket
```

### Bước 7 — Chạy bot

```bash
bash run_all.sh           # chạy cả 2 agent trong screen
screen -r agent1          # xem Agent 1
screen -r agent2          # xem Agent 2
# Thoát khỏi screen mà KHÔNG dừng agent: Ctrl+A rồi D
```

---

## Điều chỉnh bot (không cần restart)

### Thay đổi tiêu chí lọc whale → sửa `criterion.md`

```markdown
<!-- Ví dụ thêm rule mới bằng tiếng Việt -->
Bổ sung: Loại ví có net_pnl âm dù win rate cao
- net_pnl < -500 USDC → loại, lý do "negative_pnl"
- Tối thiểu 30 markets closed mới tính win rate (tránh may mắn ngắn hạn)
```

Compile ngay: `python agent1_whale_hunter/criterion_compiler.py --force`
Hoặc chờ Agent 1 tự reload lần tới (~1 giờ).

### Bật/tắt copy → sửa `wallet.md` (hiệu lực sau 15 giây)

```
AUTO_COPY=on/off      # copy theo Agent 1
MANUAL_COPY=on/off    # copy ví chỉ định tay
MAX_TOTAL_BUDGET=500  # tổng USDC tối đa
STOP_LOSS_PCT=30      # stop loss %
```

### Thêm ví copy tay → sửa `wallet.md`

```markdown
## Manual Wallets
0xWHALE_ADDRESS | 75 | crypto | Chú thích của bạn
```

---

## Cấu trúc file

```
polymarket_2agent_bot/
│
├── README.md                       ← 👈 File này
├── requirements.txt                ← Thư viện Python cần cài
├── setup.sh                        ← Cài đặt tự động
├── run_all.sh / run_agent1.sh / run_agent2.sh
│
├── skill/                          ← Tài liệu kỹ thuật
│   ├── SKILL.md                    ← Tổng quan kiến trúc
│   ├── AGENT1.md / AGENT2.md
│   ├── API_REFERENCE.md
│   └── TROUBLESHOOTING.md
│
├── agent1_whale_hunter/
│   ├── agent1_whale_hunter.py      ← Code Agent 1
│   ├── criterion.md                ← ✏️ EDIT ĐỂ THAY ĐỔI TIÊU CHÍ
│   ├── criterion_compiler.py       ← AI compiler (criterion → filter_rules)
│   └── filter_rules.py             ← 🚫 Auto-generated, ĐỪNG sửa tay
│
├── agent2_copy_trader/
│   ├── agent2_copy_trader.py       ← Code Agent 2
│   └── wallet.md                   ← ✏️ EDIT ĐỂ CẤU HÌNH
│
└── shared/
    ├── polymarket_client.py        ← Thư viện gọi API
    ├── .env.example / .env         ← Cấu hình (🔑 .env KHÔNG share)
    ├── copy_queue.jsonl            ← Hàng đợi A1→A2 (tự tạo)
    ├── db/tracked_wallets.json     ← Database ví (tự tạo)
    └── reports/                    ← Báo cáo hourly (tự tạo)
```

---

## Lệnh hay dùng

```bash
# Trạng thái
python agent1_whale_hunter/agent1_whale_hunter.py --status
tail -f shared/agent1.log
tail -f shared/agent2.log

# AI compiler
python agent1_whale_hunter/criterion_compiler.py --force   # compile ngay
python agent1_whale_hunter/criterion_compiler.py --watch   # auto-watch

# Reset
rm -f shared/db/tracked_wallets.json   # reset DB
rm -f shared/copy_queue.jsonl          # reset queue
rm -f shared/.queue_cursor             # reset cursor
```

---

## Tài liệu chi tiết

| File | Nội dung |
|------|----------|
| `skill/SKILL.md` | Kiến trúc, công thức, config reference |
| `skill/AGENT1.md` | Pipeline S1-S4, criterion compiler flow |
| `skill/AGENT2.md` | AUTO/MANUAL modes, EIP-712, wallet.md |
| `skill/API_REFERENCE.md` | Tất cả Polymarket API endpoints |
| `skill/TROUBLESHOOTING.md` | Lỗi thường gặp + cách fix |
