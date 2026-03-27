#!/usr/bin/env python3
"""
filter_rules.py — Auto-generated from criterion.md (no Anthropic API needed)
"""

def evaluate(stats: dict) -> tuple:
    """Return (passed: bool, reason: str)."""
    if not stats:
        return False, "no_data"

    # Extract metrics
    wr = stats.get('win_rate', 0)
    total_pnl = stats.get('total_pnl', 0)
    kelly = stats.get('kelly', 0)
    avg_size = stats.get('avg_size', 0)
    total_volume = stats.get('total_volume', 0)
    account_age = stats.get('account_age_days', 0)
    total_closed = stats.get('total_closed', 0)
    trades_per_month = stats.get('trades_per_month', 0)
    bot_flag = stats.get('bot_flag', 0)
    bot_round = stats.get('bot_round', False)
    bot_interval = stats.get('bot_interval', False)
    bot_hf = stats.get('bot_hf', False)
    bot_micro = stats.get('bot_micro', False)
    market_count = stats.get('market_count', 0)

    # Bot FAIL
    if bot_flag:
        return False, "BOT"
    if bot_hf:
        return False, "BOT:hf"
    if bot_round:
        return False, "BOT:round_sizes"
    if bot_interval:
        return False, "BOT:interval"
    if bot_micro:
        return False, "BOT:micro"

    # Basic PASS thresholds
    if wr < 55.0:
        return False, f"low_wr:{wr:.1f}%"
    if total_closed < 5:
        return False, "few_closed"
    if account_age < 90:
        return False, f"too_new:{account_age}d"
    if trades_per_month > 150:
        return False, "hf"
    if market_count < 3:
        return False, "few_markets"
    
    # High-confidence bias check (sure bet only)
    high_conf_ratio = stats.get('high_price_entry_ratio', 0)
    if high_conf_ratio > 0.8:
        return False, "high_conf_bias"

    # Specialist check (passes all above + specialist criteria)
    is_specialist = all([
        avg_size >= 1000,
        total_closed <= 150,
        market_count <= 20,
        total_volume >= 50000,
        wr >= 55,
        kelly >= 0.15,
        account_age >= 90
    ])
    if is_specialist:
        return True, "SPECIALIST"

    return True, ""


def score(stats: dict) -> float:
    """Return numeric score 0-1 for wallet (after evaluate passed)."""
    wr = stats.get('win_rate', 0)
    total_pnl = stats.get('total_pnl', 0)
    kelly = stats.get('kelly', 0)
    avg_size = stats.get('avg_size', 0)
    total_volume = stats.get('total_volume', 0)
    account_age = stats.get('account_age_days', 0)
    market_count = stats.get('market_count', 0)

    s = 0.0
    s += 0.2 * (1.0 if kelly >= 0.4 else (0.7 if kelly >= 0.2 else 0.0))
    s += 0.15 * (1.0 if wr >= 70 else (0.7 if wr >= 60 else 0.0))
    s += 0.15 * (1.0 if total_pnl >= 5000 else (0.7 if total_pnl >= 1000 else 0.3))
    s += 0.15 * (1.0 if total_volume >= 500000 else (0.7 if total_volume >= 200000 else 0.3))
    s += 0.1 * (1.0 if avg_size >= 1000 else (0.7 if avg_size >= 500 else 0.0))
    s += 0.1 * min(1.0, account_age / 365)
    s += 0.05 * min(1.0, market_count / 20)
    s += 0.1 * (1.0 if wr > 60 and kelly > 0.4 else 0.0)

    if stats.get('specialist'):
        s = max(s, 0.95)

    return round(s, 4)


# EOF
