import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

ALLOWED_MARKETS = ("XAU-USD.P", "XAG-USD.P", "WTI-USD.P", "BTC-USD.P")
COMMODITY_MARKETS = ALLOWED_MARKETS
DEFAULT_MAX_LEVERAGE = {
    "XAU-USD.P": 20,
    "XAG-USD.P": 20,
    "WTI-USD.P": 20,
    "BTC-USD.P": 20,
}


@dataclass
class FeeConfig:
    maker_pct: float
    taker_pct: float


@dataclass
class MarginConfig:
    # Initial margin allocated to each new trade, as percent of live equity.
    per_trade_initial_margin_pct: float

    @property
    def target_margin_ratio_pct(self) -> float:
        # Backward-compatible name used by older log messages.
        return self.per_trade_initial_margin_pct


@dataclass
class GridConfig:
    levels_per_side: Optional[int]
    spacing_pct: Optional[float]
    order_size: Optional[str]


@dataclass
class PnlConfig:
    # Leveraged ROI on the position's initial margin.
    take_profit_roi_pct: float
    stop_loss_roi_pct: float
    max_close_slippage_pct: float
    enforce_slippage_on_stop_loss: bool

    @property
    def take_profit_fee_multiple(self) -> float:
        return self.take_profit_roi_pct

    @property
    def stop_loss_fee_multiple(self) -> float:
        return self.stop_loss_roi_pct


@dataclass
class BotConfig:
    poll_interval_sec: float
    dry_run: bool
    log_level: str
    dry_run_margin_usd: float


@dataclass
class AppConfig:
    markets: list[str]
    api_base_url: str
    leverage: int
    maker_timeout_sec: float
    entry_offset_ticks: int
    entry_offset_pct: float
    max_active_trades: int
    min_signal_score: int
    candle_resolution: str
    candle_periods: int
    rsi_buy_below: float
    rsi_sell_above: float
    max_spread_pct: float
    min_spread_pct: float
    min_round_trip_profit_pct: float
    fee_buffer_pct: float
    close_reprice_sec: float
    max_mark_oracle_diff_pct: float
    margin: MarginConfig
    fees: FeeConfig
    grid: GridConfig
    pnl: PnlConfig
    bot: BotConfig
    key_id: Optional[str]
    api_secret: Optional[str]

    def max_leverage_for(self, market: str) -> int:
        return DEFAULT_MAX_LEVERAGE.get(market, self.leverage)


def _load_markets(raw: dict) -> list[str]:
    markets = raw.get("markets") or ([raw["market"]] if raw.get("market") else ALLOWED_MARKETS)
    markets = list(dict.fromkeys(markets))
    unsupported = [m for m in markets if m not in ALLOWED_MARKETS]
    if unsupported:
        allowed = ", ".join(ALLOWED_MARKETS)
        raise ValueError(f"Unsupported market(s): {unsupported}. Allowed markets: {allowed}")
    return markets


def load_config(path: str | Path) -> AppConfig:
    load_dotenv()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    bot = raw.get("bot", {})
    margin = raw.get("margin", {})
    fees = raw.get("fees", {})
    grid = raw.get("grid", {})
    pnl = raw.get("pnl", {})
    strategy = raw.get("strategy", {})

    leverage = int(raw.get("leverage", 20))
    if leverage != 20:
        raise ValueError("This strategy is configured for 20x leverage only.")

    return AppConfig(
        markets=_load_markets(raw),
        api_base_url=raw.get("api", {}).get("base_url", "https://api.ondoperps.xyz"),
        leverage=leverage,
        maker_timeout_sec=float(strategy.get("maker_timeout_sec", 45)),
        entry_offset_ticks=int(strategy.get("entry_offset_ticks", 1)),
        entry_offset_pct=float(strategy.get("entry_offset_pct", 0.003)),
        max_active_trades=int(strategy.get("max_active_trades", 3)),
        min_signal_score=int(strategy.get("min_signal_score", 4)),
        candle_resolution=str(strategy.get("candle_resolution", "15")),
        candle_periods=int(strategy.get("candle_periods", 240)),
        rsi_buy_below=float(strategy.get("rsi_buy_below", 50)),
        rsi_sell_above=float(strategy.get("rsi_sell_above", 50)),
        max_spread_pct=float(strategy.get("max_spread_pct", 0.12)),
        min_spread_pct=float(strategy.get("min_spread_pct", 0.03)),
        min_round_trip_profit_pct=float(strategy.get("min_round_trip_profit_pct", 0.0)),
        fee_buffer_pct=float(strategy.get("fee_buffer_pct", 0.003)),
        close_reprice_sec=float(strategy.get("close_reprice_sec", 5)),
        max_mark_oracle_diff_pct=float(strategy.get("max_mark_oracle_diff_pct", 0.25)),
        margin=MarginConfig(
            per_trade_initial_margin_pct=float(
                margin.get(
                    "per_trade_initial_margin_pct",
                    margin.get("initial_margin_pct", margin.get("target_margin_ratio_pct", margin.get("usage_pct", 15))),
                )
            ),
        ),
        fees=FeeConfig(
            maker_pct=float(fees.get("maker_pct", 0.0095)),
            taker_pct=float(fees.get("taker_pct", 0.02375)),
        ),
        grid=GridConfig(
            levels_per_side=grid.get("levels_per_side"),
            spacing_pct=grid.get("spacing_pct"),
            order_size=grid.get("order_size"),
        ),
        pnl=PnlConfig(
            take_profit_roi_pct=float(
                pnl.get("take_profit_roi_pct", pnl.get("take_profit_margin_pct", pnl.get("take_profit_fee_multiple", 4.0)))
            ),
            stop_loss_roi_pct=float(
                pnl.get("stop_loss_roi_pct", pnl.get("stop_loss_margin_pct", pnl.get("stop_loss_fee_multiple", 6.0)))
            ),
            max_close_slippage_pct=float(pnl.get("max_close_slippage_pct", 0.02)),
            enforce_slippage_on_stop_loss=bool(pnl.get("enforce_slippage_on_stop_loss", False)),
        ),
        bot=BotConfig(
            poll_interval_sec=float(bot.get("poll_interval_sec", 3)),
            dry_run=bool(bot.get("dry_run", True)),
            log_level=str(bot.get("log_level", "INFO")),
            dry_run_margin_usd=float(bot.get("dry_run_margin_usd", 5000)),
        ),
        key_id=os.getenv("ONDO_KEY_ID"),
        api_secret=os.getenv("ONDO_API_SECRET"),
    )



