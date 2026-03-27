# Whale Selection Criteria
# ─────────────────────────────────────────────────────────────────────────────
# FILE NÀY DO BẠN VIẾT — AI SẼ TỰ ĐỌC VÀ VIẾT CODE PYTHON
#
# ✅ Viết bằng tiếng Việt hoặc tiếng Anh, không cần format cố định
# ✅ Thay đổi file này → Agent 1 tự compile lại filter_rules.py (~1 giờ)
# ✅ Compile ngay lập tức: python criterion_compiler.py --force
#
# ❌ ĐỪNG sửa filter_rules.py trực tiếp — sẽ bị ghi đè lần tới
# ─────────────────────────────────────────────────────────────────────────────

## 1. Kelly Criterion — đo lường "edge" thật sự của ví

Kelly Criterion là công thức tài chính để đo lường lợi thế (edge) thống kê.
Ví có Kelly dương nghĩa là họ dự đoán tốt hơn ngẫu nhiên một cách nhất quán.

Công thức:
```
Kelly fraction = (win_rate * avg_odds - loss_rate) / avg_odds
avg_odds = (1 - avg_entry_price) / avg_entry_price
```

Ngưỡng:
- Kelly > 0.15 → ví tốt (có edge thật sự, đáng tin)
- Kelly 0.05–0.15 → ví trung bình (edge yếu nhưng còn dương)
- Kelly < 0.05 hoặc âm → loại (không có edge, hoặc đang thua dần)


## 2. Điều kiện cơ bản để qualify (PASS/FAIL)

### PASS — đủ điều kiện theo dõi:
- Win rate > 55% (tính trên tối thiểu **3** thị trường đã resolve)
  Lý do: 3 markets đủ để đánh giá win rate, mở rộng pool specialist.
- Lịch sử > **3 tháng** (first trade cách hiện tại > **90 ngày**)
  Lý do: Track record đủ dài nhưng không quá restrictive.
- Số trades/tháng ≤ **150**
- **Số closed positions tối thiểu ≥ 20**
  Lý do: Cần đủ dữ liệu để win rate và Kelly đáng tin, tránh false positive.
- Tổng số thị trường đã tham gia ≥ **3**

### FAIL — Loại bot (không copy bot):
- > 500 trades/tháng → high frequency automated trading [bot_hf]
- > 90% trades là bội số 100 USDC chính xác → round size bot [bot_round]
  Ví dụ: $100, $200, $500, $1000 — con người thường dùng số lẻ
- Thời gian trade đều đặn CV < 10% → robot clock [bot_interval]
  CV = Coefficient of Variation = std / mean của khoảng cách giữa trades
- > 70% trades tập trung vào 3 giờ cố định trong ngày → latency sniper [bot_latency_sniper]
  Giải thích: Polymarket có 15-min crypto markets với lag 30-90s giữa giá thật
  và giá Polymarket. Bot sniper vào ngay trước expire để capture delta chắc chắn.
  Đây là algo trade không thể replicable bằng tay — không nên copy.
- avg size < $5 với > 200 trades/tháng → micro spam / wash trading [bot_micro]
- >60% trades có entry price > $0.90 → BOND_TRADER (không copy vì chỉ là risk-free yield, không có directional insight) [bond_trader]

### FAIL — Loại suspicious (cần thận trọng):
- Tài khoản mới < 10 trades nhưng size > $5,000 → suspicious
- Win rate > 90% trên > 30 thị trường → có thể insider, flag để review
  Lý do: Win rate 90%+ trên 30+ markets gần như không thể bằng kỹ năng thuần túy


## 3. Nhóm ví (Cluster Detection)

Phát hiện nhiều ví cùng thuộc 1 whale lớn (tách ví để tránh bị phát hiện):

Tiêu chí gom nhóm:
- Cùng vào 1 market (condition_id giống nhau)
- Size trade tương đương (chênh lệch < 20%)
- Trong cùng time window 24–48 giờ
- ≥ 3 ví trong cùng nhóm → tính là cluster

Khi phát hiện cluster: tính tổng size của nhóm, dùng làm "effective whale size"


## 4. Category Filter

Chỉ theo dõi các category sau (nếu API trả về category field):
- geopolitics (elections, wars, treaties, sanctions)
- crypto (price targets, ETF, regulation, adoption)
- sports (championships, match outcomes, player events)

Bỏ qua: entertainment, weather, misc
Lưu ý: Hiện tại API không trả về category field đáng tin cậy,
nên category_diversity trong stats thường = 0. Filter này có thể bỏ qua.


## 5. The Signal — Khi nào trigger copy trade

Điều kiện kích hoạt báo hiệu copy:
```
signal_strength = (wallets_entering_same_outcome / total_basket_wallets)
```

- signal_strength > 0.80 → STRONG SIGNAL (nhiều whale cùng lúc → tin tưởng cao)
- signal_strength 0.60–0.80 → MODERATE SIGNAL (theo dõi thêm)
- signal_strength < 0.60 → WEAK / NO SIGNAL

Thêm điều kiện:
- Entries xảy ra trong 24–48 giờ (tight time window — cùng thông tin)
- Giá hiện tại còn cách resolve > 5¢ (spread favorable — còn upside)


## 6. Scoring weights (gợi ý cho AI khi tạo hàm score())

Trọng số ưu tiên:
- Kelly fraction: quan trọng nhất (35%)
- Win rate: quan trọng (30%)
- Total volume/depth: thứ yếu (15%)
- Account age: thứ yếu (10%)
- Category diversity: ít quan trọng (10%) — thường = 0


## 7. Output format cho daily report

File lưu tại: shared/reports/whale_report_YYYY-MM-DD_HH.md
Bao gồm:
- Danh sách ví đủ điều kiện + Kelly score + win rate + avg size
- Ví bị loại + lý do ngắn gọn
- Active signals (nếu có)


## 8. Specialist Whale Detection (Optimal Copy Targets)

**Mục tiêu**: Xác định các whale có đặc điểm sau:
- Trade rất lớn (avg_size >= $1,000)
- Trades rất ít (total_trades <= 150)
- Chuyên sâu 1-2 markets (market_diversity <= 20)
- Có vốn lớn (total_volume >= $50,000)
- Không phải bot

**Tại sao quan trọng**: Những ví này thường có edge thông tin sâu về một chuyên môn cụ thể.
Trade lớn + ít lần → có tâm, không phải ngẫu nhiên. Chuyên sâu → edge thông tin.

**Tiêu chí Specialist**:
- avg_size_usd >= 1000  (giảm từ 20000 → dễ tiếp cận hơn)
- total_trades <= 150  (cho phép nhiều trade hơn, thay vì 50)
- market_diversity <= 20
- total_volume_usd >= 50000  (giảm từ 200000)
- win_rate >= 55
- kelly >= 0.15
- account_age_days >= 90
- bot_flag = false
- suspicious_flag = false

**Relaxed requirements cho Specialists**:
Vì specialists trade ít, số closed positions có thể thấp.
Thay vì min_closed_markets >= 20, dùng min_closed_markets >= **5** cho specialists.

**Position scaling**:
Khi specialist được promote, gán `specialist_bonus = True` trong metadata.
Agent 2 sẽ scale position size lớn hơn (ví dụ: base_volume * 2) cho specialists.

**Nghịch lý cần lưu ý**:
- Specialist có thể có win rate/Kelly cao trên 1-2 market nhưng không generalize.
- Risk: Overfitting vào 1 market, nếu market chiều ngược lại có thể thua lớn.
- Mitigation: Theo dõi real-time performance, nếu drawdown >20% thì tạm dừng.

**Implementation**:
- Khi filter_rules.evaluate() chạy, nếu ví đạt specialist criteria, trả về (True, "")
- Thêm trường `is_specialist` vào snapshot để wallet.md highlight.
