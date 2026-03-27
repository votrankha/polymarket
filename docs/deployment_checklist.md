# Deployment Checklist — Polymarket Bot

**Before going live with real money, complete all items below.**

---

## 📦 Phase 1: Prerequisites

- [ ] **Environment ready:** Python 3.12+, virtualenv created (`venv/`)
- [ ] **Dependencies installed:** `pip install -r requirements.txt`
- [ ] **Database initialized:** `shared/db/polybot.db` exists and tables created
- [ ] **Agent 1 code:** `agent1_whale_hunter/` present and tested
- [ ] **Agent 2 code:** `agent2_copy_trader/` present and tested

---

## 🔐 Phase 2: Credentials & Security

- [ ] **`.env` file configured** in `/root/polymarket/shared/` with:
  - `WALLET_ADDRESS` (your proxy wallet, 0x...)
  - `PRIVATE_KEY` (without 0x prefix)
  - `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE` (from Polymarket API)
  - `ENABLE_NEW_METRICS=false` (initially)
  - `MAX_TOTAL_BUDGET` set appropriately
- [ ] **Private key permissions:** 0o600 (chmod 600)
- [ ] **Backup:** `shared/.env.backup` created (outside repo)
- [ ] **Testnet first:** If possible, test on testnet before mainnet

---

## 🧪 Phase 3: Testing

- [ ] **Agent 1 test:** Run `python agent1_whale_hunter/agent1_whale_hunter.py --test` (if supported)
- [ ] **Agent 2 simulation:** Run `analysis/filler_rules_simulation.py --scenario A` and review P&L
- [ ] **Health check:** `python scripts/health_check.py` — all green
- [ ] **Log monitoring:** `tail -f shared/agent1.log` shows no errors for 30 min
- [ ] **Database growth:** Verified snapshots and trades accumulating

---

## ⚙️ Phase 4: Agent 2 Configuration

- [ ] **`wallet.md` settings:**
  - `AUTO_COPY=off` (if only using manual specialists)
  - `MANUAL_COPY=on`
  - `MAX_TOTAL_BUDGET` matches your risk appetite
  - `MAX_PER_MARKET` set (e.g., 100)
  - `STOP_LOSS_PCT` set (e.g., 30)
  - `MAX_OPEN_POSITIONS` set (e.g., 10)
- [ ] **Manual Wallets:** Only trusted specialists added with correct budgets
- [ ] **Blacklist:** Any known bad wallets added

---

## 🚀 Phase 5: Initial Deployment

- [ ] **Start Agent 1:** 
  ```bash
  cd /root/polymarket
  nohup ./venv/bin/python agent1_whale_hunter/agent1_whale_hunter.py > shared/agent1.log 2>&1 &
  ```
- [ ] **Verify Agent 1 running:** `ps aux | grep agent1_whale_hunter.py`
- [ ] **Monitor initial logs:** `tail -30 shared/agent1.log` (no errors)
- [ ] **Start Agent 2 (if doing live copy):**
  ```bash
  nohup ./venv/bin/python agent2_copy_trader/agent2_copy_trader.py > shared/agent2.log 2>&1 &
  ```
- [ ] **Verify Agent 2 running:** `ps aux | grep agent2_copy_trader.py`

---

## 👁️ Phase 6: Monitoring (First 24h)

- [ ] **Every 30 min:** Check `agent1.log` for errors
- [ ] **Every hour:** Check DB size: `ls -lh shared/db/polybot.db`
- [ ] **Every 2h:** Verify wallet_snapshots count increasing
- [ ] **Check Agent 2:** If running, review `shared/agent2.log` for trade executions
- [ ] **Balance check:** Ensure wallet balance sufficient for MAX_TOTAL_BUDGET

---

## 📊 Phase 7: Evaluation (After 24h)

- [ ] **Stop Agent 1** (if doing batch analysis) or continue 24/7
- [ ] **Run performance analysis:** `python analysis/agent1_performance.py`
- [ ] **Run filler simulation:** `python analysis/filler_rules_simulation.py --scenario all`
- [ ] **Review results:** Is ROI consistent? Any anomalies?
- [ ] **Adjust if needed:** Update `wallet.md` specialists or budgets

---

## 🛠️ Phase 8: Ongoing Operations

- [ ] **Daily research:** `python analysis/daily_market_research.py` each morning
- [ ] **Heartbeat monitoring:** Check HEARTBEAT.md schedule
- [ ] **Weekly review:** Re-run full analysis, adjust filler rules
- [ ] **Backup DB:** Periodic backup of `polybot.db`
- [ ] **Log rotation:** Set up logrotate for `shared/*.log`

---

## ⚠️ Risk Management

- [ ] **Max drawdown limit:** Know your max acceptable loss
- [ ] **Stop-loss enabled:** `STOP_LOSS_PCT` set in `wallet.md`
- [ ] **Budget caps:** `MAX_TOTAL_BUDGET` and `MAX_PER_MARKET` enforced
- **Never** use more than you can afford to lose
- **Always** keep API keys and private keys secure

---

## 📞 Emergency Contacts

- **Shutdown:** `pkill -f agent1_whale_hunter.py` and `pkill -f agent2_copy_trader.py`
- **Check status:** `python scripts/health_check.py`
- **View logs:** `tail -f shared/agent1.log` and `tail -f shared/agent2.log`

---

**Deployment completed by:** _________________  
**Date:** _________________  
**Initial capital committed:** $_________________
