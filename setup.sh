#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  Polymarket 2-Agent Bot — Setup Script
#  Chạy 1 lần duy nhất sau khi upload code lên VPS
# ═══════════════════════════════════════════════════════════

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Polymarket 2-Agent Bot — Setup${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"

# 1. Python version check
echo -e "\n${YELLOW}[1/6] Checking Python...${NC}"
python3 --version || { echo "Python3 not found. Install: sudo apt install python3"; exit 1; }
PYVER=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYVER" -lt 10 ]; then
  echo "Python 3.10+ required (found 3.$PYVER)"
  exit 1
fi
echo "  ✓ Python OK"

# 2. System deps
echo -e "\n${YELLOW}[2/6] Installing system dependencies...${NC}"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip screen curl
echo "  ✓ System deps OK"

# 3. Virtualenv
echo -e "\n${YELLOW}[3/6] Creating virtualenv...${NC}"
python3 -m venv venv
echo "  ✓ venv created"

# 4. Python packages
echo -e "\n${YELLOW}[4/6] Installing Python packages...${NC}"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
echo "  ✓ Packages installed"

# 5. Directories + .env
echo -e "\n${YELLOW}[5/6] Creating directories...${NC}"
mkdir -p shared/reports shared/db
touch shared/agent1.log shared/agent2.log
chmod +x run_agent1.sh run_agent2.sh run_all.sh

if [ ! -f shared/.env ]; then
  cp shared/.env.example shared/.env
  echo -e "  ${YELLOW}⚠  Created shared/.env from example — FILL IN YOUR KEYS!${NC}"
else
  echo "  ✓ shared/.env already exists"
fi
echo "  ✓ Directories OK"

# 6. Done
echo -e "\n${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Fill in your keys:"
echo "     nano shared/.env"
echo ""
echo "  2. Seed whale DB (first run):"
echo "     source venv/bin/activate"
echo "     python agent1_whale_hunter/agent1_whale_hunter.py --bootstrap"
echo ""
echo "  3. Run both agents:"
echo "     bash run_all.sh"
echo ""
echo "  4. Monitor:"
echo "     screen -r agent1"
echo "     screen -r agent2"
echo ""
