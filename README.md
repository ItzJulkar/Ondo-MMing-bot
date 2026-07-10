# Ondo MMing Bot

A paired maker-order bot for Ondo Perps. It is designed for XAU, XAG, and BTC only.

## What It Does

For each market, the bot places a paired maker setup:

1. A post-only buy order at the current orderbook bid.
2. A post-only sell order about `0.015%` above the buy price.
3. If one side fills, the opposite side is kept as the close order.
4. If the position is loss/flat, the close waits at `loss_close_profit_pct` target. If it is in profit, the close is re-quoted at the current maker side after `close_reprice_sec`.

Current default markets:

- `XAU-USD.P`
- `XAG-USD.P`
- `BTC-USD.P`

The bot does not commit API keys. Put keys only in `.env`.

Emergency stop-loss: if an open position reaches the configured `stop_loss_roi_pct` loss, the bot cancels its open bot orders for that market and sends a reduce-only market close.

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
```

Safe exit without opening new trades:

```powershell
python -m src.main safe-exit
```

`safe-exit` stops creating any new entry pairs immediately. If BTC has not opened yet, its pending bot orders are cancelled. If XAU/XAG/BTC already has a position, the bot keeps only the maker close order for that position, re-quotes it as usual, and automatically stops after all bot positions/orders are flat.

Force stop only when you want the bot process to stop immediately:

```powershell
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

Safe exit the bot:

```bash
python3 -m src.main safe-exit
```

Force stop the bot:

```bash
python3 -m src.main stop
```


## If Notepad Opens Blank

If `.env` or `config.yaml` opens blank, you are probably not inside the bot folder or the copy command failed. Run this first:

```powershell
cd $env:USERPROFILE\Ondo-MMing-bot
dir
```

You should see these files:

```text
.env.example
config.example.yaml
requirements.txt
src
```

Then copy again:

```powershell
copy .env.example .env
copy config.example.yaml config.yaml
notepad .env
notepad config.yaml
```

Paste this into `.env` and replace with your own Ondo API keys:

```env
ONDO_KEY_ID=ondoKeyId_YOUR_KEY_ID
ONDO_API_SECRET=ondoApiSecret_YOUR_SECRET
```

Paste this into `config.yaml` if it is blank:

```yaml
markets:
  - XAU-USD.P
  - XAG-USD.P
  - BTC-USD.P

api:
  base_url: https://api.ondoperps.xyz

leverage: 20

strategy:
  maker_timeout_sec: 10
  max_active_trades: 7
  min_spread_pct: 0.0
  max_spread_pct: 0.12
  min_round_trip_profit_pct: 0.015
  close_reprice_sec: 3
  max_mark_oracle_diff_pct: 0.25

margin:
  per_trade_initial_margin_pct: 30

fees:
  maker_pct: 0.0095
  taker_pct: 0.02375

pnl:
  take_profit_roi_pct: 2.0
  stop_loss_roi_pct: 2.0
  max_close_slippage_pct: 0.02
  enforce_slippage_on_stop_loss: false

bot:
  poll_interval_sec: 3
  dry_run: true
  dry_run_margin_usd: 5000
  log_level: INFO
```

Check that config loads before live trading:

```powershell
python -m src.main status
```

To test without live orders, keep `dry_run: true`. To trade live, change it to `dry_run: false` after your `.env` keys are correct.

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

