from decimal import Decimal

from src.grid.levels import align_price, build_grid_levels
from src.models import GridLevel, MarketInfo, MarketSnapshot, Side


def post_only_buy_cap(price: Decimal, best_bid: Decimal, increment: Decimal) -> Decimal:
    """Maker buy must sit below the best bid to avoid post_only_has_match."""
    cap = best_bid - increment
    return min(price, cap) if cap > 0 else price


def post_only_sell_floor(price: Decimal, best_ask: Decimal, increment: Decimal) -> Decimal:
    """Maker sell must sit above the best ask."""
    floor = best_ask + increment
    return max(price, floor)


def build_smart_grid(
    snapshot: MarketSnapshot,
    market_info: MarketInfo,
    buy_levels: int,
    sell_levels: int,
    spacing_pct: float,
) -> list[GridLevel]:
    """
    Place grid around Ondo mark price (used for uPnL/liquidation).

    Rules:
    - Anchor on mark, not mid (Ondo docs)
    - Buys below mark, sells above (mean-reversion grid)
    - Snap to postOnly-safe prices vs current book
    - First level at least 1 spacing from anchor
    """
    levels = build_grid_levels(
        anchor=snapshot.mark_price,
        market_info=market_info,
        buy_levels=buy_levels,
        sell_levels=sell_levels,
        spacing_pct=spacing_pct,
        market=snapshot.market,
    )

    safe: list[GridLevel] = []
    inc = market_info.quote_increment
    for level in levels:
        price = level.price
        if level.side == Side.BUY:
            price = post_only_buy_cap(price, snapshot.best_bid, inc)
        else:
            price = post_only_sell_floor(price, snapshot.best_ask, inc)
        price = align_price(price, inc)
        safe.append(
            GridLevel(price=price, side=level.side, client_order_id=level.client_order_id)
        )
    return safe


def needs_rebalance(anchor: Decimal, mark: Decimal, spacing_pct: float, threshold_levels: float = 2.0) -> bool:
    """Recenter grid when price drifts ≥ N spacings from last anchor."""
    if anchor <= 0:
        return True
    drift_pct = abs(float(mark - anchor) / float(anchor) * 100)
    return drift_pct >= spacing_pct * threshold_levels