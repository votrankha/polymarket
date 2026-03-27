# Cài đặt SQLite History System

## Files mới trong bản này
- `shared/db_store.py`          ← SQLite layer (tự tạo schema lần đầu)
- `scripts/result_tracker.py`   ← Cập nhật kết quả copy trades (chạy hourly)
- `agent1_whale_hunter.py`      ← Đã được patch tích hợp DB (không cần patch thêm)

## Bước 1 — Upload lên VPS
```bash
# Chỉ cần upload 2 file mới + file agent1 đã patch
scp shared/db_store.py          user@vps:/root/Polymarket/bot_claude/polybot2/shared/
scp scripts/result_tracker.py   user@vps:/root/Polymarket/bot_claude/polybot2/
scp agent1_whale_hunter/agent1_whale_hunter.py \
    user@vps:/root/Polymarket/bot_claude/polybot2/agent1_whale_hunter/
```

## Bước 2 — Test db_store
```bash
cd /root/Polymarket/bot_claude/polybot2
source venv/bin/activate
python shared/db_store.py
# Nếu thấy "✅ All tests passed" → OK
```

## Bước 3 — Restart Agent 1
```bash
screen -X -S agent1 quit
bash run_agent1.sh

# Kiểm tra log — phải thấy dòng này khi khởi động:
# [db_store] whale_trades=0  snapshots=0  copy_trades=0  (0.0MB)
```

## Bước 4 — Chạy result_tracker (cập nhật kết quả copy trades)
```bash
# Thêm screen riêng
screen -dmS tracker bash -c "
  source venv/bin/activate
  python result_tracker.py --watch
"
screen -r tracker  # xem log
```

## Kiểm tra DB sau khi chạy
```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from shared.db_store import get_db
db = get_db()
print(db.get_stats())
"
# Output mẫu sau vài giờ:
# {'whale_trades': 1247, 'wallet_snapshots': 23, 'copy_trades': 5, 'markets': 18, 'db_size_mb': 0.8}
```

## Database location
`shared/db/polybot.db` — 1 file SQLite duy nhất
```bash
# Backup
cp shared/db/polybot.db shared/db/polybot.db.bak

# Query trực tiếp bằng sqlite3
sqlite3 shared/db/polybot.db "SELECT address, win_rate, kelly, score FROM wallet_snapshots ORDER BY ts DESC LIMIT 10;"
sqlite3 shared/db/polybot.db "SELECT status, COUNT(*), SUM(pnl_usdc) FROM copy_trades GROUP BY status;"
```
