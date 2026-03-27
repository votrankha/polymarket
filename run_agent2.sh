#!/bin/bash
# Run Agent 2 — Copy Trader
cd "$(dirname "$0")"
source venv/bin/activate

if [ "$1" == "--auto" ]; then
  echo "[Agent2] Starting with AUTO mode forced on..."
  python agent2_copy_trader/agent2_copy_trader.py --auto
elif [ "$1" == "--manual" ]; then
  echo "[Agent2] Starting with MANUAL mode forced on..."
  python agent2_copy_trader/agent2_copy_trader.py --manual
elif [ "$1" == "--status" ]; then
  python agent2_copy_trader/agent2_copy_trader.py --status
else
  echo "[Agent2] Starting (mode from wallet.md)..."
  python agent2_copy_trader/agent2_copy_trader.py
fi
