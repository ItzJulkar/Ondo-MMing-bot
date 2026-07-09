from decimal import Decimal

from src.config import AppConfig
from src.grid.regime import VOLATILITY_MULTIPLIER, session_spacing_multiplier
from src.models import Session


def round_trip_fee_pct(config: AppConfig) -> float:
    return config.fees.maker_pct + config.fees.taker_pct


def min_profitable_move_pct(config: AppConfig) -> float:
    notional_factor = (config.margin.target_margin_ratio_pct / 100) * 2 * config.leverage
    if notional_factor <= 0:
        return 1.0
    gross_move = config.pnl.take_profit_margin_pct / notional_factor
    return gross_move + round_trip_fee_pct(config)


def compute_grid_spacing_pct(
    config: AppConfig,
    market: str,
    atr_pct: float | None = None,
    session: Session = Session.REGULAR,
) -> float:
    """
    Per-asset spacing:
    - Fee floor (must exceed round-trip cost for 2% TP)
    - ATR component (35% of hourly range — captures mean-reversion zone)
    - XAG multiplier (silver moves wider than gold)
    - Weekend multiplier (wider grids, less churn)
    """
    fee_floor = min_profitable_move_pct(config) * 1.15
    vol_mult = VOLATILITY_MULTIPLIER.get(market, 1.0)
    vol_component = (atr_pct or fee_floor) * 0.35 * vol_mult
    spacing = max(fee_floor, vol_component)
    spacing = min(spacing, min_profitable_move_pct(config) * 2.0)
    spacing *= session_spacing_multiplier(session)
    return round(max(spacing, 0.05), 4)


def compute_levels_per_side(config: AppConfig, margin_balance: Decimal, num_markets: int) -> int:
    if config.grid.levels_per_side is not None:
        return max(1, min(int(config.grid.levels_per_side), 10))

    from src.risk.sizing import calc_initial_margin

    per_level = calc_initial_margin(margin_balance, config.margin.target_margin_ratio_pct)
    if per_level <= 0:
        return 2

    budget_per_market = margin_balance * Decimal("0.30") / Decimal(num_markets)
    levels = int(budget_per_market / per_level)
    return max(2, min(levels, 4))