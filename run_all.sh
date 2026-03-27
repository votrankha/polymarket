#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  Run both agents in separate screen sessions
# ═══════════════════════════════════════════════════════════
cd "$(dirname "$0")"

echo ""
echo "  Polymarket 2-Agent Bot"
echo "  ─────────────────────────────────────────────"

# Kill existing screens if running
screen -X -S agent1 quit 2>/dev/null && echo "  Stopped existing agent1 screen"
screen -X -S agent2 quit 2>/dev/null && echo "  Stopped existing agent2 screen"

sleep 1

# Start Agent 1
screen -dmS agent1 bash -c "
  cd $(pwd)
  source venv/bin/activate
  echo '[Agent1] Starting...'
  python agent1_whale_hunter/agent1_whale_hunter.py 2>&1 | tee -a shared/agent1.log
"
echo "  ✓ Agent 1 started  (screen: agent1)"

sleep 2

# Start Agent 2
screen -dmS agent2 bash -c "
  cd $(pwd)
  source venv/bin/activate
  echo '[Agent2] Starting...'
  python agent2_copy_trader/agent2_copy_trader.py 2>&1 | tee -a shared/agent2.log
"
echo "  ✓ Agent 2 started  (screen: agent2)"

echo ""
echo "  Commands:"
echo "    screen -r agent1   # attach Agent 1 log"
echo "    screen -r agent2   # attach Agent 2 log"
echo "    Ctrl+A D           # detach (keep running)"
echo ""
echo "  Logs:"
echo "    tail -f shared/agent1.log"
echo "    tail -f shared/agent2.log"
echo ""
