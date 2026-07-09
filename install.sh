#!/bin/bash
# Ondo grid bot — Debian/Ubuntu install & start
set -e

cd "$(dirname "$0")"
echo "=== Ondo Grid Bot Installer ==="

if ! command -v python3 &>/dev/null; then
    echo "Installing Python 3..."
    apt update
    apt install -y python3 python3-pip python3-venv
fi

echo "Python: $(python3 --version)"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env with your Ondo API keys:"
    echo "  nano .env"
    echo ""
fi

if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
fi

echo ""
echo "=== Installed ==="
echo "Next steps:"
echo "  1. nano .env          # add API keys"
echo "  2. nano config.yaml     # set dry_run: false for live trading"
echo "  3. source venv/bin/activate"
echo "  4. python3 -m src.main start"
echo ""
echo "  Stop:   python3 -m src.main stop"
echo "  Status: python3 -m src.main status"
echo "  Logs:   tail -f logs/bot.log"