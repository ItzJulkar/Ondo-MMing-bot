import argparse
import logging
from decimal import Decimal
from pathlib import Path

from src.bot import GridBot
from src.config import load_config
from src.daemon import clear_stop, show_status, start_background, stop_background
from src.exchange import MockOndoClient, OndoClient


def build_exchange(config):
    if config.bot.dry_run:
        return MockOndoClient(
            markets=config.markets,
            margin_balance=Decimal(str(config.bot.dry_run_margin_usd)),
        )
    if not config.key_id or not config.api_secret:
        raise SystemExit(
            "Live mode requires ONDO_KEY_ID and ONDO_API_SECRET in .env.\n"
            "Set dry_run: true in config.yaml to simulate first."
        )
    return OndoClient(config.api_base_url, config.key_id, config.api_secret)


def run_bot(config_path: Path) -> None:
    config = load_config(config_path)
    LOG_DIR = config_path.parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, config.bot.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    mode = "DRY-RUN" if config.bot.dry_run else "LIVE"
    logging.getLogger(__name__).info("Bot process started [%s] — runs 24/7 until stopped", mode)

    exchange = build_exchange(config)
    GridBot(config, exchange).run()
    clear_stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ondo XAU/XAG grid bot — start/stop 24/7 trading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  start   Start bot in background (runs 24/7)
  stop    Stop the running bot
  status  Check if bot is running
  run     Run in foreground (Ctrl+C to stop)

Examples:
  python -m src.main start
  python -m src.main stop
  python -m src.main status
        """,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=["start", "stop", "status", "run"],
        help="start=background 24/7 (default), stop=halt, status=check, run=foreground",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to config YAML")
    args = parser.parse_args()

    config_path = Path(args.config)
    if args.command != "status" and not config_path.exists():
        example = config_path.parent / "config.example.yaml"
        raise SystemExit(f"Config not found: {config_path}\nCopy {example.name} to {config_path.name}")

    if args.command == "start":
        start_background(str(config_path))
    elif args.command == "stop":
        stop_background()
    elif args.command == "status":
        show_status()
    elif args.command == "run":
        run_bot(config_path)


if __name__ == "__main__":
    main()