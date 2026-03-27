#!/bin/bash
# Watchdog để restart Agent 1 nếu log không update trong 30 phút
# Usage: /root/polymarket/scripts/watchdog_agent1.sh

LOG_FILE="/root/polymarket/shared/agent1.log"
PID_FILE="/root/polymarket/shared/agent1.pid"
AGENT_CMD="cd /root/polymarket && nohup python3 agent1_whale_hunter/agent1_whale_hunter.py > /dev/null 2>&1 &"

# Check last log entry timestamp
if [ -f "$LOG_FILE" ]; then
    LAST_LINE=$(tail -1 "$LOG_FILE" | awk '{print $1" "$2}')
    if [ -n "$LAST_LINE" ]; then
        LAST_EPOCH=$(date -d "$LAST_LINE" +%s 2>/dev/null || echo 0)
        NOW_EPOCH=$(date +%s)
        AGE_MIN=$(( (NOW_EPOCH - LAST_EPOCH) / 60 ))

        if [ $AGE_MIN -gt 30 ]; then
            echo "$(date '+%H:%M:%S') [WATCHDOG] Log stale ($AGE_MIN min). Restarting Agent 1..."
            pkill -f "agent1_whale_hunter.py" 2>/dev/null
            sleep 2
            eval $AGENT_CMD
            echo $! > "$PID_FILE"
            echo "$(date '+%H:%M:%S') [WATCHDOG] Agent 1 restarted (PID $!)"
        else
            echo "$(date '+%H:%M:%S') [WATCHDOG] Log fresh ($AGE_MIN min). No action."
        fi
    else
        echo "$(date '+%H:%M:%S') [WATCHDOG] Empty log. Starting Agent 1..."
        pkill -f "agent1_whale_hunter.py" 2>/dev/null
        sleep 2
        eval $AGENT_CMD
        echo $! > "$PID_FILE"
        echo "$(date '+%H:%M:%S') [WATCHDOG] Agent 1 started (PID $!)"
    fi
else
    echo "$(date '+%H:%M:%S') [WATCHDOG] Log file missing. Starting Agent 1..."
    pkill -f "agent1_whale_hunter.py" 2>/dev/null
    sleep 2
    eval $AGENT_CMD
    echo $! > "$PID_FILE"
    echo "$(date '+%H:%M:%S') [WATCHDOG] Agent 1 started (PID $!)"
fi
