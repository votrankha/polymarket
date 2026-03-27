#!/bin/bash
# Run Agent 1 — Whale Hunter
cd "$(dirname "$0")"
source venv/bin/activate

if [ "$1" == "--bootstrap" ]; then
  echo "[Agent1] Bootstrap mode — seeding DB from leaderboard..."
  python agent1_whale_hunter/agent1_whale_hunter.py --bootstrap
elif [ "$1" == "--status" ]; then
  python agent1_whale_hunter/agent1_whale_hunter.py --status
elif [ "$1" == "--report" ]; then
  python agent1_whale_hunter/agent1_whale_hunter.py --report
else
  echo "[Agent1] Starting in full pipeline mode..."
  python agent1_whale_hunter/agent1_whale_hunter.py
fi
