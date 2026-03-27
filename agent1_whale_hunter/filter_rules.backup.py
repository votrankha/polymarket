# filter_rules.py — Viết theo criterion.md
# ═══════════════════════════════════════════════════════════════════════════════
# FILE NÀY được viết dựa trên criterion.md
# Nếu bạn dùng criterion_compiler.py → file này sẽ bị ghi đè tự động.
# Nếu bạn chạy thủ công → copy file này vào agent1_whale_hunter/filter_rules.py
# ═══════════════════════════════════════════════════════════════════════════════

import math
from typing import Tuple


# ── Thresholds — tương ứng 1-1 với criterion.md ──────────────────────────────

# Kelly (criterion.md mục 1)
KELLY_GOOD     = 0.15   # Kelly > 0.15 → ví tốt
KELLY_MIN      = 0.05   # Kelly < 0.05 → loại

# PASS conditions (criterion.md mục 2)
MIN_WIN_RATE        = 60.0   # win_rate > 60%
MIN_CLOSED_MARKETS  = 10     # tối thiểu 10 markets đã resolve để tính win rate đáng tin
MIN_CLOSED_MARKETS_SPECIALIST = 5  # relaxed cho specialist (trade lớn nhưng ít)
MIN_HISTORY_DAYS    = 120    # > 4 tháng (4 * 30 = 120 ngày)
MAX_TRADES_PER_MON  = 100    # ≤ 100 trades/tháng
MIN_MARKET_COUNT    = 10     # tổng markets đã tham gia ≥ 10

# Specialist Whale criteria (criterion.md mục 8)
SPECIALIST_MIN_AVG_SIZE      = 50_000.0   # avg_size >= $50k
SPECIALIST_MAX_TRADES        = 50         # total_trades <= 50
SPECIALIST_MAX_MARKETS       = 3          # market_diversity <= 3
SPECIALIST_MIN_VOLUME        = 500_000.0  # total_volume >= $500k
SPECIALIST_MIN_AGE           = 180        # account_age_days >= 180
SPECIALIST_MIN_KATIE        = 0.1        # kelly >= 0.1 (có edge)
MIN_CLOSED_MARKETS_SPECIALIST = 5         # cần ít nhất 5 closed để đủ confidence

# Bot detection (criterion.md mục 2 - FAIL)
BOT_HF_THRESHOLD    = 100    # > 100 trades/tháng → bot_hf
BOT_ROUND_RATIO     = 0.90   # > 90% trades bội số $100 → bot_round
BOT_INTERVAL_CV     = 0.10   # CV < 10% → bot_interval (robot clock)
BOT_SNIPER_RATIO    = 0.70   # > 70% trades trong 3 giờ cố định → bot_latency_sniper
BOT_MICRO_SIZE      = 5.0    # avg_size < $5 → bot_micro
BOT_MICRO_FREQ      = 200    # VÀ > 200 trades/tháng → bot_micro

# Suspicious (criterion.md mục 2 - FAIL suspicious)
SUS_NEW_THRESHOLD   = 10     # < 10 trades nhưng size > $5k → suspicious
SUS_NEW_SIZE        = 5000.0
SUS_HIGH_WR_TRADES  = 30     # win_rate > 90% trên > 30 markets → suspicious
SUS_HIGH_WR         = 90.0

# Scoring weights (criterion.md mục 6)
WEIGHT_KELLY        = 0.35
WEIGHT_WIN_RATE     = 0.30
WEIGHT_VOLUME       = 0.15
WEIGHT_AGE          = 0.10
WEIGHT_DIVERSITY    = 0.10

# Normalisation caps cho scoring
SCORE_KELLY_CAP     = 0.30    # kelly/0.30 → 1.0
SCORE_WR_RANGE      = 40.0    # (wr - min_wr) / 40 → 1.0
SCORE_VOL_CAP       = 1_000_000.0
SCORE_AGE_CAP       = 365     # ngày


# ══════════════════════════════════════════════════════════════════════════════
#  evaluate(stats) — kiểm tra ví có đủ điều kiện không
# ══════════════════════════════════════════════════════════════════════════════

def evaluate(stats: dict) -> Tuple[bool, str]:
    """
    Kiểm tra ví theo toàn bộ tiêu chí trong criterion.md.

    Returns:
        (True,  "")           → ví đạt, tiếp tục chấm điểm
        (False, "lý_do")      → ví bị loại, lý do ngắn gọn

    Thứ tự filter: bot → suspicious → basic qualifications → kelly
    (từ dễ fail nhất → khó nhất để exit sớm)
    """
    if not stats:
        return False, "no_data"

    # ── [1] Bot detection — loại ngay nếu là bot ─────────────────────────────
    # Bot không có "edge" thật — copy bot chỉ tốn tiền
    if stats.get("bot_flag"):
        reasons = []
        if stats.get("bot_round"):
            reasons.append("round_sizes")          # >90% bội số $100
        if stats.get("bot_interval"):
            reasons.append("robot_clock")           # CV intervals < 10%
        if stats.get("bot_hf"):
            reasons.append(f"hf>{BOT_HF_THRESHOLD}/mo")  # high frequency
        if stats.get("bot_latency_sniper"):
            reasons.append("latency_sniper")        # exploit lag crypto markets
        if stats.get("bot_micro"):
            reasons.append("micro_spam")            # avg < $5, >200/tháng
        return False, "BOT:" + "+".join(reasons)

    # ── [2] Suspicious flags — loại nếu có dấu hiệu insider/gian lận ────────
    if stats.get("suspicious_flag"):
        reason = stats.get("suspicious_reason", "suspicious")
        return False, f"SUSPICIOUS:{reason}"

    # ── [3] Determine if qualifies for specialist relaxed thresholds ───────
    # Specialist whales: trade lớn, ít trades, chuyên sâu 1-2 markets
    is_specialist_candidate = (
        stats.get('avg_size', 0) >= SPECIALIST_MIN_AVG_SIZE and
        stats.get('total_trades', 0) <= SPECIALIST_MAX_TRADES and
        stats.get('market_diversity', 0) <= SPECIALIST_MAX_MARKETS and
        stats.get('total_volume', 0) >= SPECIALIST_MIN_VOLUME and
        stats.get('account_age_days', 0) >= SPECIALIST_MIN_AGE
    )

    # ── [4] Điều kiện cơ bản (PASS conditions, criterion.md mục 2) ───────────
    # Cần đủ dữ liệu để đánh giá (tránh may mắn ngắn hạn)
    total_closed = stats.get("total_closed", 0)
    # Relaxed closed markets cho specialist: chỉ yêu cầu >= 5
    min_closed_req = MIN_CLOSED_MARKETS_SPECIALIST if is_specialist_candidate else MIN_CLOSED_MARKETS
    if total_closed < min_closed_req:
        return False, f"few_closed:{total_closed}<{min_closed_req}"

    # Win rate > 60%
    win_rate = stats.get("win_rate", 0.0)
    if win_rate < MIN_WIN_RATE:
        return False, f"low_wr:{win_rate:.1f}%"

    # Lịch sử > 4 tháng
    age_days = stats.get("account_age_days", 0)
    if age_days < MIN_HISTORY_DAYS:
        return False, f"too_new:{age_days}d<{MIN_HISTORY_DAYS}d"

    # Tổng markets tham gia: relaxed cho specialist (chỉ cần >=3)
    market_count = stats.get("market_count", 0)
    min_market_req = 3 if is_specialist_candidate else MIN_MARKET_COUNT
    if market_count < min_market_req:
        return False, f"few_markets:{market_count}<{min_market_req}"

    # ── [5] Kelly Criterion (criterion.md mục 1) ──────────────────────────────
    # Kelly < 0.05 → không có edge thực sì → loại
    kelly = stats.get("kelly", 0.0)
    if kelly < KELLY_MIN:
        return False, f"low_kelly:{kelly:.4f}<{KELLY_MIN}"

    # ── [6] Specialista check — nếu là specialist với kelly tốt ─────────────
    if is_specialist_candidate:
        # Specialist phải có kelly >= 0.1 để được ghi nhận
        if kelly >= SPECIALIST_MIN_KATIE:
            return True, "SPECIALIST"
        # Nếu kelly < 0.1, specialist vẫn pass nhưng bình thường (không đặc biệt)

    # Tất cả filter đều pass
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
#  score(stats) — chấm điểm ví đã pass evaluate()
# ══════════════════════════════════════════════════════════════════════════════

def score(stats: dict) -> float:
    """
    Tính điểm tổng hợp 0.0–1.0 theo trọng số trong criterion.md mục 6:
        Kelly        35%  — edge thật sự, quan trọng nhất
        Win rate     30%  — xác suất thắng
        Volume       15%  — depth/quy mô vốn
        Age          10%  — độ tin cậy theo thời gian
        Diversity    10%  — đa dạng category (thường = 0 vì API thiếu data)

    Điểm cao hơn = ví tốt hơn = được ưu tiên theo dõi và copy.
    Chỉ gọi hàm này sau khi evaluate() trả True.
    """
    win_rate   = stats.get("win_rate", 0.0)
    kelly      = stats.get("kelly", 0.0)
    volume     = stats.get("total_volume", 0.0)
    age_days   = stats.get("account_age_days", 0)
    diversity  = stats.get("category_diversity", 0)

    # Mỗi component được normalize về 0–1 trước khi nhân trọng số
    # min(1.0, x) để cap tối đa = 1.0

    # Kelly component: kelly/0.30 (kelly=0.30 → điểm max)
    c_kelly = min(1.0, kelly / SCORE_KELLY_CAP)

    # Win rate component: phần vượt trên ngưỡng tối thiểu / 40
    # Ví dụ: wr=80% → (80-60)/40 = 0.5 | wr=100% → (100-60)/40 = 1.0
    c_wr = min(1.0, (win_rate - MIN_WIN_RATE) / SCORE_WR_RANGE)
    c_wr = max(0.0, c_wr)  # không âm

    # Volume component: volume / 1,000,000 USDC
    c_vol = min(1.0, volume / SCORE_VOL_CAP)

    # Age component: age / 365 ngày
    c_age = min(1.0, age_days / SCORE_AGE_CAP)

    # Diversity component: thường = 0 vì API không trả category
    c_div = min(1.0, diversity / 3.0)

    total = (
        c_kelly   * WEIGHT_KELLY    +
        c_wr      * WEIGHT_WIN_RATE +
        c_vol     * WEIGHT_VOLUME   +
        c_age     * WEIGHT_AGE      +
        c_div     * WEIGHT_DIVERSITY
    )

    return round(total, 4)


# ══════════════════════════════════════════════════════════════════════════════
#  describe() — trả về dict thresholds để log khi agent khởi động
# ══════════════════════════════════════════════════════════════════════════════

def describe() -> dict:
    """
    Trả về tất cả threshold đang dùng.
    Agent 1 gọi hàm này khi khởi động để log ra cho người dùng biết
    filter đang dùng thresholds gì.
    """
    return {
        # PASS conditions
        "min_win_rate":         MIN_WIN_RATE,
        "min_closed_markets":   MIN_CLOSED_MARKETS,
        "min_history_days":     MIN_HISTORY_DAYS,
        "max_trades_per_month": MAX_TRADES_PER_MON,
        "min_market_count":     MIN_MARKET_COUNT,

        # Kelly
        "min_kelly":            KELLY_MIN,
        "kelly_good":           KELLY_GOOD,

        # Bot detection
        "bot_hf_threshold":     BOT_HF_THRESHOLD,
        "bot_round_ratio":      BOT_ROUND_RATIO,
        "bot_interval_cv":      BOT_INTERVAL_CV,
        "bot_sniper_ratio":     BOT_SNIPER_RATIO,
        "bot_micro_size":       BOT_MICRO_SIZE,
        "bot_micro_freq":       BOT_MICRO_FREQ,

        # Suspicious
        "sus_new_threshold":    SUS_NEW_THRESHOLD,
        "sus_new_size":         SUS_NEW_SIZE,
        "sus_high_wr":          SUS_HIGH_WR,

        # Scoring weights
        "weights": {
            "kelly":     WEIGHT_KELLY,
            "win_rate":  WEIGHT_WIN_RATE,
            "volume":    WEIGHT_VOLUME,
            "age":       WEIGHT_AGE,
            "diversity": WEIGHT_DIVERSITY,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Self-test — chạy: python filter_rules.py
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("filter_rules.py — Self-test")
    print("=" * 60)
    print(f"\nThresholds đang dùng:\n{json.dumps(describe(), indent=2, ensure_ascii=False)}")
    print()

    # Danh sách test cases — mỗi case là 1 loại ví điển hình
    test_cases = [
        # (tên mô tả, stats dict)
        ("✅ Whale tốt — kelly cao, wr cao", {
            "win_rate": 75.0, "total_closed": 45, "wins": 34, "losses": 11,
            "net_pnl": 8500.0, "total_volume": 120000.0, "avg_size": 500.0,
            "trades_per_month": 20.0, "account_age_days": 300, "kelly": 0.22,
            "kelly_b": 2.5, "market_count": 45, "category_diversity": 2,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 60,
        }),
        ("✅ Whale trung bình — kelly yếu nhưng vẫn pass", {
            "win_rate": 63.0, "total_closed": 25, "wins": 16, "losses": 9,
            "net_pnl": 1200.0, "total_volume": 30000.0, "avg_size": 200.0,
            "trades_per_month": 15.0, "account_age_days": 180, "kelly": 0.08,
            "kelly_b": 1.8, "market_count": 25, "category_diversity": 1,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 40,
        }),
        ("❌ Bot — high frequency", {
            "win_rate": 68.0, "total_closed": 200, "wins": 136, "losses": 64,
            "net_pnl": 3000.0, "total_volume": 500000.0, "avg_size": 150.0,
            "trades_per_month": 150.0, "account_age_days": 400, "kelly": 0.18,
            "kelly_b": 2.0, "market_count": 200, "category_diversity": 3,
            "bot_flag": True, "bot_round": False, "bot_interval": False,
            "bot_hf": True, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 450,
        }),
        ("❌ Bot — latency sniper", {
            "win_rate": 88.0, "total_closed": 60, "wins": 53, "losses": 7,
            "net_pnl": 12000.0, "total_volume": 80000.0, "avg_size": 300.0,
            "trades_per_month": 30.0, "account_age_days": 250, "kelly": 0.45,
            "kelly_b": 5.0, "market_count": 60, "category_diversity": 1,
            "bot_flag": True, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": True, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 90,
        }),
        ("❌ Suspicious — win rate > 90% trên > 30 markets", {
            "win_rate": 93.0, "total_closed": 45, "wins": 42, "losses": 3,
            "net_pnl": 25000.0, "total_volume": 200000.0, "avg_size": 1000.0,
            "trades_per_month": 10.0, "account_age_days": 500, "kelly": 0.55,
            "kelly_b": 7.0, "market_count": 45, "category_diversity": 2,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": True, "suspicious_reason": "win_rate>90%",
            "total_trades": 30,
        }),
        ("❌ Win rate thấp", {
            "win_rate": 45.0, "total_closed": 30, "wins": 14, "losses": 16,
            "net_pnl": -500.0, "total_volume": 15000.0, "avg_size": 100.0,
            "trades_per_month": 8.0, "account_age_days": 200, "kelly": 0.0,
            "kelly_b": 1.2, "market_count": 30, "category_diversity": 1,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 25,
        }),
        ("❌ Tài khoản quá mới", {
            "win_rate": 70.0, "total_closed": 22, "wins": 15, "losses": 7,
            "net_pnl": 800.0, "total_volume": 10000.0, "avg_size": 200.0,
            "trades_per_month": 15.0, "account_age_days": 45, "kelly": 0.12,
            "kelly_b": 2.0, "market_count": 22, "category_diversity": 1,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 30,
        }),
        ("❌ Kelly quá thấp", {
            "win_rate": 62.0, "total_closed": 25, "wins": 16, "losses": 9,
            "net_pnl": 100.0, "total_volume": 20000.0, "avg_size": 150.0,
            "trades_per_month": 10.0, "account_age_days": 200, "kelly": 0.02,
            "kelly_b": 1.1, "market_count": 25, "category_diversity": 1,
            "bot_flag": False, "bot_round": False, "bot_interval": False,
            "bot_hf": False, "bot_latency_sniper": False, "bot_micro": False,
            "suspicious_flag": False, "suspicious_reason": "",
            "total_trades": 30,
        }),
    ]

    passed_count = 0
    for name, stats in test_cases:
        ok, reason = evaluate(stats)
        if ok:
            sc = score(stats)
            print(f"{name}")
            print(f"   → PASS  score={sc:.4f}  "
                  f"(kelly={stats['kelly']:.3f} wr={stats['win_rate']:.0f}% "
                  f"age={stats['account_age_days']}d)")
            passed_count += 1
        else:
            print(f"{name}")
            print(f"   → FAIL  reason={reason}")
        print()

    print(f"Kết quả: {passed_count}/{len(test_cases)} ví pass")
