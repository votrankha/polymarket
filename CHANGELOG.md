# Polymarket Bot — Changelog

All notable changes to the Polymarket trading bot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **Automatic wallet.md update**: Agent 1 now appends promoted wallets directly to `wallet.md` immediately upon promotion (no waiting for hourly report). Format: `ADDRESS | BUDGET | all | NOTE` (specialist $200, normal $100).
- **Filter rules optimizer**: New `optimize_filter_rules.py` script analyzes DB to find optimal scoring weights and thresholds based on actual ROI correlation.

### Changed
- **Relaxed filter thresholds** (criterion.md):
  - Win rate: `>60%` → `>55%`
  - Minimum closed markets: `10` → `5`
  - Account age: `>4 months` → `>3 months`
  - **markets_count threshold: `≥5` → `≥3`** (2026-03-27, to include high-quality 3-4 market specialists from Mina's monitor list)
  - Specialist criteria:
    - avg_size: `$50k` → `$20k`
    - total_volume: `$500k` → `$200k`
    - total_trades: `≤50` (unchanged)
    - win_rate: `≥60` → `≥55`
    - kelly: `≥0.1` → `≥0.15`
    - account_age: `≥180d` → `≥120d`
- **Scoring weights** (optimized):
  - Kelly: 0.20 (↑ from 0.10)
  - Total PnL: 0.35 (new primary metric)
  - Volume: 0.15 (new)
  - Win rate: 0.15 (↓ from 0.30)
  - Avg size: 0.10 (↓ from 0.20)
  - Account age: 0.10
  - Market diversity: 0.05
  - Consistency: 0.10

### Fixed
- **criterion_compiler.py**: Rewritten to be rule-based, removing dependency on ANTHROPIC_API_KEY. Now directly parses `criterion.md` and generates `filter_rules.py` without external AI calls.
- **filter_rules.py** API: Now correctly implements `evaluate(stats) -> (bool, reason)` and `score(stats) -> float` as expected by Agent 1.
- **Agent 1 startup**: Increased timeouts in compiler and ensured proper module imports.

### Known Issues
- API credentials (`.env`) still placeholder; live trading requires real Polymarket API keys.
- Wallet pool expansion ongoing; currently only 2 wallets promoted (target >20 for robust simulation).
- copy_queue.jsonl activity depends on credentials to fetch real-time wallet trades.

---

## [2026-03-14] — Initial Release (ver_1.2)

### Added
- Multi-agent architecture: Agent 1 (Whale Hunter) + Agent 2 (Copy Trader)
- WebSocket real-time trade detection with REST fallback
- Closed positions analytics (using `/closed-positions` endpoint)
- Kelly criterion integration
- Bot detection (high frequency, round sizes, interval regularity, micro trades)
- Specialist Whale Detection (high-conviction, low-diversification traders)
- File-based IPC via `copy_queue.jsonl` with byte cursor
- Hot-reload configuration via `criterion.md` → `filter_rules.py` compiler
- Hourly reports and `wallet.md` auto-generation
- Health checks and daily market research automation

### Fixed
- Data source correctness: using `/closed-positions` for win rate (not `/trades`)
- Gamma API deprecation: switched to `data-api.polymarket.com`
- Environment variable loading: `load_dotenv(override=True)` at startup
- WebSocket subscribe format: correct `channel: "market"` with single `assets_id`
- Output format: JSON for machine parseability
- Graceful shutdown and signal handling
- Permissions: umask 0o177 for secure output files

---

*Last updated: 2026-03-18*