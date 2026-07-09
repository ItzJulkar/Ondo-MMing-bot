"""One-shot API check — shows balance, mark prices, trend, and computed grid params."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.exchange.ondo import OndoClient
from src.grid.regime import detect_session, detect_trend
from src.grid.strategy import GridStrategy


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config.yaml")
    if not config.key_id or not config.api_secret:
        raise SystemExit("Missing ONDO_KEY_ID or ONDO_API_SECRET in .env")

    client = OndoClient(config.api_base_url, config.key_id, config.api_secret)
    balance = client.get_balance()
    session = detect_session()

    print("API connection OK")
    print(f"  Session:           {session.value}")
    print(f"  Margin balance:    ${balance.margin_balance}")
    print(f"  Available margin:  ${balance.available_margin}")

    for market in config.markets:
        snap = client.get_market_snapshot(market)
        closes = client.get_hourly_closes(market)
        trend = detect_trend(closes)
        snap.trend = trend
        strat = GridStrategy(config, client, market)
        params = strat.resolve_params(snap, balance.margin_balance)
        can, reason = strat.should_trade(snap, balance.margin_balance, balance.available_margin)

        print(f"\n  {market}")
        print(f"    Mark:      ${snap.mark_price}")
        print(f"    Trend:     {trend.value}")
        print(f"    Spacing:   {params['spacing']:.4f}%")
        print(f"    Size:      {params['size']}")
        print(f"    Grid:      {params['buy_levels']} buys / {params['sell_levels']} sells")
        print(f"    Can trade: {can} ({reason})")


if __name__ == "__main__":
    main()