# VPS Tutorial

This guide runs Ondo MMing Bot 24/7 on a Debian or Ubuntu VPS.

## 1. Connect To VPS

```bash
ssh root@YOUR_SERVER_IP
```

## 2. Install System Packages

```bash
apt update
apt install -y git python3 python3-pip python3-venv
```

## 3. Download The Bot

```bash
cd /root
git clone https://github.com/ItzJulkar/Ondo-MMing-bot.git
cd Ondo-MMing-bot
```

## 4. Install Python Dependencies

```bash
chmod +x install.sh
./install.sh
```

## 5. Add Your API Keys

```bash
nano .env
```

Example:

```env
ONDO_KEY_ID=ondoKeyId_YOUR_KEY_ID
ONDO_API_SECRET=ondoApiSecret_YOUR_SECRET
```

Never upload `.env` to GitHub.

## 6. Configure The Bot

```bash
nano config.yaml
```

For testing, keep:

```yaml
bot:
  dry_run: true
```

For live trading:

```yaml
bot:
  dry_run: false
```

## 7. Start / Stop / Logs

```bash
source venv/bin/activate
python3 -m src.main start
python3 -m src.main status
tail -f logs/bot.log
python3 -m src.main stop
```

## Notes

- VPS helps keep the bot online even if your PC turns off.
- Maker orders can sit in queue and are not guaranteed to fill instantly.
- If the bot is rate-limited, increase cooldowns or reduce active markets.

