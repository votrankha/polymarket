# TROUBLESHOOTING.md — Debug & Xử Lý Lỗi

## Kiểm tra nhanh hệ thống

```bash
# Trạng thái Agent 1 DB
python agent1_whale_hunter/agent1_whale_hunter.py --status

# Trạng thái Agent 2
python agent2_copy_trader/agent2_copy_trader.py --status

# Xem log realtime
tail -f shared/agent1.log
tail -f shared/agent2.log

# Đếm tasks trong queue
wc -l shared/copy_queue.jsonl

# Xem tasks gần nhất (đọc được định dạng đẹp)
tail -5 shared/copy_queue.jsonl | python -m json.tool

# Kiểm tra filter_rules.py hiện tại
python3 -c "
import sys; sys.path.insert(0, 'agent1_whale_hunter')
from filter_rules import describe
print(describe())
"
```

---

## Lỗi thường gặp

### ❌ `PRIVATE_KEY not set in shared/.env`

**Nguyên nhân:** File `.env` chưa tồn tại hoặc chưa điền key.

```bash
cp shared/.env.example shared/.env
nano shared/.env
# Điền WALLET_ADDRESS và PRIVATE_KEY
```

---

### ❌ `Insufficient USDC: 0.00 < 25.00`

**Nguyên nhân:** Proxy wallet chưa có USDC.

```bash
# Kiểm tra số dư
python3 -c "
import os; from dotenv import load_dotenv
load_dotenv('shared/.env')
print('Wallet:', os.getenv('WALLET_ADDRESS'))
"
# Sau đó nạp USDC vào địa chỉ trên, mạng Polygon
```

---

### ❌ `[DB] Loaded 0 wallets` sau bootstrap

**Nguyên nhân:** Tất cả ví đều bị discard bởi filter_rules.

```bash
# Xem lý do discard
grep "DISCARD" shared/agent1.log | tail -30

# Nếu thấy nhiều "low_wr" hay "low_kelly" → tiêu chí quá nghiêm
# Sửa criterion.md: giảm ngưỡng win rate hoặc kelly
# Ví dụ thêm vào criterion.md:
# "Thử nghiệm: giảm win rate tối thiểu xuống 50%"
# "Giảm Kelly tối thiểu xuống 0.03"

# Sau đó compile lại ngay
python agent1_whale_hunter/criterion_compiler.py --force

# Chạy bootstrap lại
python agent1_whale_hunter/agent1_whale_hunter.py --bootstrap
```

---

### ❌ Agent 2 không copy gì (AUTO mode)

Kiểm tra từng bước:

```bash
# Bước 1: Queue có tasks không?
wc -l shared/copy_queue.jsonl
# Nếu 0 → Agent 1 chưa detect được whale nào

# Bước 2: Cursor có bị stuck không?
cat shared/.queue_cursor          # offset hiện tại
wc -c shared/copy_queue.jsonl    # tổng byte trong file
# Nếu cursor >= tổng byte → đã đọc hết, chờ task mới

# Bước 3: wallet.md có AUTO_COPY=on không?
grep "AUTO_COPY" agent2_copy_trader/wallet.md

# Bước 4: Active Wallets có entries không?
grep "^0x" agent2_copy_trader/wallet.md

# Bước 5: Log Agent 2
grep "AUTO\|SKIP\|wallet not in" shared/agent2.log | tail -20
```

**Reset cursor (đọc lại queue từ đầu):**
```bash
rm shared/.queue_cursor   # Agent 2 sẽ đọc lại từ đầu
```

---

### ❌ Agent 2 không copy gì (MANUAL mode)

```bash
# 1. MANUAL_COPY=on?
grep "MANUAL_COPY" agent2_copy_trader/wallet.md

# 2. Có ví trong ## Manual Wallets không?
grep -A 10 "## Manual Wallets" agent2_copy_trader/wallet.md

# 3. Log Agent 2
grep "MANUAL\|poll" shared/agent2.log | tail -20
```

---

### ❌ `Invalid signature` khi đặt lệnh

**Nguyên nhân:** Private key không khớp với wallet address.

```bash
python3 -c "
from eth_account import Account
import os
from dotenv import load_dotenv
load_dotenv('shared/.env')
key = os.getenv('PRIVATE_KEY')
if not key.startswith('0x'):
    key = '0x' + key
acc = Account.from_key(key)
print('Address from key:', acc.address)
print('Configured addr: ', os.getenv('WALLET_ADDRESS'))
print('Match:', acc.address.lower() == os.getenv('WALLET_ADDRESS','').lower())
"
```

---

### ❌ filter_rules.py bị lỗi sau khi sửa criterion.md

```bash
# Xem file lỗi AI đã tạo
cat agent1_whale_hunter/filter_rules.FAILED.py

# Xem backup (bản trước khi compile lần này)
cat agent1_whale_hunter/filter_rules.backup.py

# Bot đang dùng bản nào?
# → Rollback tự động về backup khi compile fail
# → Nếu muốn dùng backup: cp filter_rules.backup.py filter_rules.py

# Thử viết lại criterion.md rõ ràng hơn, rồi force compile
python agent1_whale_hunter/criterion_compiler.py --force
```

---

### ❌ `429 Too Many Requests` từ Polymarket API

**Nguyên nhân:** Scan quá nhanh.

```bash
# Tăng interval trong .env, rồi restart agent
TRACKING_INTERVAL=30
HISTORY_BATCH=4
POLL_INTERVAL=15
```

---

### ❌ `wallet.md không được update bởi Agent 1`

```bash
# Kiểm tra section header đúng không
grep "## Active Wallets" agent2_copy_trader/wallet.md

# Nếu không có → thêm vào
echo -e "\n## Active Wallets\n# Agent 1 tự ghi vào đây" >> agent2_copy_trader/wallet.md
```

---

### ❌ `encode_structured_data ImportError`

```bash
# Lỗi tương thích phiên bản eth-account
pip install "eth-account==0.10.0" --break-system-packages
```

---

## Đọc hiểu log

### Log Agent 1 bình thường
```
[S1] $24,500  0xba664f999a18dce0...  YES  mkt:0xdef456...
  [S2] 0xba664f999a18dce0...
  [S3] ✓ PROMOTED 0xba664f999a18dce0...  score=0.84  wr=72.1%  kelly=0.213  age=312d
[QUEUE ▶] YES $24,500  Will Bitcoin exceed $100k?
[REPORT] Written: whale_report_2025-01-15_14.md  (23 wallets)
[wallet.md] Updated — 23 wallets
[criterion] Compiling filter_rules.py...  ✅ done
```

### Log Agent 2 bình thường
```
[wallet.md] Reloaded — AUTO=ON  MANUAL=ON  auto_wallets=23  manual_wallets=2
[AUTO] 🔔 WHALE TRADE
   Wallet  : 0xba664f999a18dce0...
   Market  : Will Bitcoin exceed $100k by Dec 2026?
   Outcome : YES @ 0.6503  whale=$24,500
   Copying : $50.00 USDC
  ↳ ✓ ORDER PLACED  0xORDER_HASH...
```

### Red flags cần chú ý
```
# Nhiều DISCARD → tiêu chí quá khắt khe, nới lỏng criterion.md
[S3] DISCARD 0xabc... low_wr:34.5%

# Task bị skip vì ví không còn trong Active Wallets
[AUTO] Task wallet 0xabc... not in auto_wallets, skip

# Order fail liên tục
✗ FAILED: Insufficient USDC    → nạp thêm USDC
✗ FAILED: Invalid signature    → check PRIVATE_KEY
✗ FAILED: Market not tradeable → market đã đóng

# filter_rules compile fail
[compiler] Validation FAILED: Missing functions: {'score'}  → criterion.md không rõ ràng
```

---

## Reset hoàn toàn

```bash
# Reset DB — bootstrap lại khi Agent 1 start
rm -f shared/db/tracked_wallets.json

# Reset queue và cursor
rm -f shared/copy_queue.jsonl shared/.queue_cursor

# Xóa logs
> shared/agent1.log
> shared/agent2.log

# Xóa reports
rm -f shared/reports/whale_report_*.md

# Reset filter_rules (dùng lại backup)
cp agent1_whale_hunter/filter_rules.backup.py agent1_whale_hunter/filter_rules.py
rm -f agent1_whale_hunter/.criterion_hash  # force recompile lần tới
```

---

## Monitor với screen

```bash
bash run_all.sh          # chạy cả 2 agent

screen -r agent1         # xem Agent 1 (Ctrl+A D để thoát không dừng)
screen -r agent2         # xem Agent 2

screen -ls               # liệt kê tất cả sessions
screen -X -S agent1 quit # dừng Agent 1
screen -X -S agent2 quit # dừng Agent 2
```

---

## Cron (nếu muốn bootstrap định kỳ thay vì chạy liên tục)

```cron
# Bootstrap mỗi 4 giờ
0 */4 * * * cd /opt/polymarket_bot && \
  ./venv/bin/python agent1_whale_hunter/agent1_whale_hunter.py \
  --bootstrap >> shared/agent1_cron.log 2>&1

# Force report mỗi giờ
0 * * * * cd /opt/polymarket_bot && \
  ./venv/bin/python agent1_whale_hunter/agent1_whale_hunter.py \
  --report >> shared/agent1_cron.log 2>&1
```
