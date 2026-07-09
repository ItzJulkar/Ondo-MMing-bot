from decimal import Decimal, ROUND_DOWN

from src.models import GridLevel, MarketInfo, Side


def align_price(price: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return price
    steps = (price / increment).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return steps * increment


def build_grid_levels(
    anchor: Decimal,
    market_info: MarketInfo,
    buy_levels: int,
    sell_levels: int,
    spacing_pct: float,
    market: str | None = None,
) -> list[GridLevel]:
    spacing = anchor * Decimal(str(spacing_pct / 100))
    if spacing <= 0:
        raise ValueError("spacing_pct must produce a positive spacing")

    market_name = market or market_info.market
    prefix = market_name.replace("-", "_").replace(".", "_")
    levels: list[GridLevel] = []

    for i in range(1, buy_levels + 1):
        buy_price = align_price(anchor - spacing * i, market_info.quote_increment)
        levels.append(
            GridLevel(
                price=buy_price,
                side=Side.BUY,
                client_order_id=f"grid_{prefix}_buy_{i}",
            )
        )

    for i in range(1, sell_levels + 1):
        sell_price = align_price(anchor + spacing * i, market_info.quote_increment)
        levels.append(
            GridLevel(
                price=sell_price,
                side=Side.SELL,
                client_order_id=f"grid_{prefix}_sell_{i}",
            )
        )

    return levels