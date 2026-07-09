# Ondo MMing Bot

A paired maker-order bot for Ondo Perps. It is designed for XAU, XAG, and BTC only.

## What It Does

For each market, the bot places a paired maker setup:

1. A post-only buy order at the current orderbook bid.
2. A post-only sell order about `0.015%` above the buy price.
3. If one side fills, the opposite side is kept as the close order.
4. If the close order does not fill, it is cancelled and re-quoted at the current maker side after `close_reprice_sec`.

Current default markets:

- `XAU-USD.P`
- `XAG-USD.P`
- `BTC-USD.P`

The bot does not commit API keys. Put keys only in `.env`.

## Risk Notes

This is live trading software. Maker orders are not guaranteed to fill instantly. If price moves away before the close fills, unrealized loss can happen. Use dry-run first and start with small balances.

## Windows PC Setup

Open PowerShell:

```powershell
cd "C:\Users\YourName"
git clone https://github.com/ItzJulkar/Ondo-MMing-bot.git
cd Ondo-MMing-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
copy config.example.yaml config.yaml
notepad .env
notepad config.yaml
```

Add your own Ondo API keys in `.env`:

```env
ONDO_KEY_ID=ondoKeyId_YOUR_KEY_ID
ONDO_API_SECRET=ondoApiSecret_YOUR_SECRET
```

Start in dry-run first:

```powershell
python -m src.main run
```

For live trading, set this in `config.yaml`:

```yaml
bot:
  dry_run: false
```

Then run in background:

```powershell
python -m src.main start
python -m src.main status
python -m src.main stop
```

## VPS Setup

Use a Debian/Ubuntu VPS. SSH into the VPS:

```bash
ssh root@YOUR_SERVER_IP
apt update
apt install -y git python3 python3-pip python3-venv
```

Clone and install:

```bash
cd /root
git clone https://github.com/ItzJulkar/Ondo-MMing-bot.git
cd Ondo-MMing-bot
chmod +x install.sh
./install.sh
```

Edit secrets and config:

```bash
nano .env
nano config.yaml
```

Start the bot:

```bash
source venv/bin/activate
python3 -m src.main start
python3 -m src.main status
tail -f logs/bot.log
```

Stop the bot:

```bash
python3 -m src.main stop
```

## Important Files

- `.env.example`: example only, never put real keys in GitHub.
- `.env`: real keys, ignored by git.
- `config.example.yaml`: safe starter config.
- `config.yaml`: your local live config, can be edited per machine.

## Default Strategy Settings

```yaml
strategy:
  maker_timeout_sec: 10
  min_round_trip_profit_pct: 0.015
  close_reprice_sec: 3

margin:
  per_trade_initial_margin_pct: 30

bot:
  poll_interval_sec: 3
  dry_run: true
```

