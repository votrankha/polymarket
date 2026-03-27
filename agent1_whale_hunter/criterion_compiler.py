#!/usr/bin/env python3
"""
criterion_compiler.py — Parse criterion.md directly, no external APIs
Generates filter_rules.py based on thresholds and weights defined in criterion.md
"""

import re
from pathlib import Path

CRITERION_FILE = Path(__file__).parent / "criterion.md"
OUTPUT_FILE = Path(__file__).parent / "filter_rules.py"

def parse_criterion():
    """Extract thresholds and weights from criterion.md"""
    text = CRITERION_FILE.read_text(encoding="utf-8")
    
    # Defaults
    params = {
        "win_rate_threshold": 55.0,
        "min_closed": 5,
        "account_age_days": 90,
        "max_trades_per_month": 150,
        "min_markets": 5,
        "specialist_avg_size_usd": 1000,
        "specialist_total_trades": 150,
        "specialist_market_diversity": 20,
        "specialist_total_volume_usd": 50000,
        "specialist_win_rate": 55,
        "specialist_kelly": 0.15,
        "specialist_account_age_days": 90,
        "weight_kelly": 0.20,
        "weight_win_rate": 0.15,
        "volume_weight": 0.15,
        "weight_avg_size": 0.10,
        "weight_account_age": 0.10,
        "weight_market_div": 0.05,
        "weight_consistency": 0.10,
        "weight_total_pnl": 0.15,
    }
    
    # Parse from criterion.md (same patterns as before)
    m = re.search(r"Win rate\s*>\s*(\d+)%", text)
    if m:
        params["win_rate_threshold"] = float(m.group(1))
    
    m = re.search(r"tối thiểu\s*\*\*(\d+)\*\*", text)
    if m:
        params["min_closed"] = int(m.group(1))
    
    m = re.search(r">\s*(\d+)\s*tháng", text)
    if m:
        params["account_age_days"] = int(m.group(1)) * 30
    
    m = re.search(r"Số trades/tháng\s*≤\s*(\d+)", text)
    if m:
        params["max_trades_per_month"] = int(m.group(1))
    
    m = re.search(r"Tổng số thị trường.*?≥\s*(\d+)", text)
    if m:
        params["min_markets"] = int(m.group(1))
    
    m = re.search(r"avg_size_usd\s*>=\s*(\d+)", text)
    if m:
        params["specialist_avg_size_usd"] = int(m.group(1))
    
    m = re.search(r"total_trades\s*<=\s*(\d+)", text)
    if m:
        params["specialist_total_trades"] = int(m.group(1))
    
    m = re.search(r"market_diversity\s*<=\s*(\d+)", text)
    if m:
        params["specialist_market_diversity"] = int(m.group(1))
    
    m = re.search(r"total_volume_usd\s*>=\s*(\d+)", text)
    if m:
        params["specialist_total_volume_usd"] = int(m.group(1))
    
    m = re.search(r"win_rate\s*>=\s*(\d+)", text)
    if m:
        params["specialist_win_rate"] = int(m.group(1))
    
    m = re.search(r"kelly\s*>=\s*([\d.]+)", text)
    if m:
        params["specialist_kelly"] = float(m.group(1))
    
    m = re.search(r"account_age_days\s*>=\s*(\d+)", text)
    if m:
        params["specialist_account_age_days"] = int(m.group(1))
    
    return params

def generate_code(params):
    """Generate filter_rules.py content based on params"""
    # Using a single multi-line string with proper escaping
    code = f'''#!/usr/bin/env python3
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
    if wr < {params['win_rate_threshold']}:
        return False, f"low_wr:{{wr:.1f}}%"
    if total_closed < {params['min_closed']}:
        return False, "few_closed"
    if account_age < {params['account_age_days']}:
        return False, f"too_new:{{account_age}}d"
    if trades_per_month > {params['max_trades_per_month']}:
        return False, "hf"
    if market_count < {params['min_markets']}:
        return False, "few_markets"

    # Specialist check (passes all above + specialist criteria)
    is_specialist = all([
        avg_size >= {params['specialist_avg_size_usd']},
        total_closed <= {params['specialist_total_trades']},
        market_count <= {params['specialist_market_diversity']},
        total_volume >= {params['specialist_total_volume_usd']},
        wr >= {params['specialist_win_rate']},
        kelly >= {params['specialist_kelly']},
        account_age >= {params['specialist_account_age_days']}
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
    s += {params['weight_kelly']} * (1.0 if kelly >= 0.4 else (0.7 if kelly >= 0.2 else 0.0))
    s += {params['weight_win_rate']} * (1.0 if wr >= 70 else (0.7 if wr >= 60 else 0.0))
    s += {params['weight_total_pnl']} * (1.0 if total_pnl >= 5000 else (0.7 if total_pnl >= 1000 else 0.3))
    s += {params['volume_weight']} * (1.0 if total_volume >= 500000 else (0.7 if total_volume >= 200000 else 0.3))
    s += {params['weight_avg_size']} * (1.0 if avg_size >= 1000 else (0.7 if avg_size >= 500 else 0.0))
    s += {params['weight_account_age']} * min(1.0, account_age / 365)
    s += {params['weight_market_div']} * min(1.0, market_count / 20)
    s += {params['weight_consistency']} * (1.0 if wr > 60 and kelly > 0.4 else 0.0)

    if stats.get('specialist'):
        s = max(s, 0.95)

    return round(s, 4)


# EOF
'''
    return code

def compile_criterion():
    """Generate filter_rules.py from criterion.md."""
    params = parse_criterion()
    code = generate_code(params)
    OUTPUT_FILE.write_text(code, encoding="utf-8")
    return params

def load_filter_rules():
    """Dynamically load the generated filter_rules module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("filter_rules", str(OUTPUT_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def main():
    print("🔧 Compiling filter_rules.py from criterion.md...")
    params = compile_criterion()
    print(f"✅ Generated {OUTPUT_FILE} ({len(generate_code(params))} bytes)")
    print("📋 Parameters used:")
    for k, v in params.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
