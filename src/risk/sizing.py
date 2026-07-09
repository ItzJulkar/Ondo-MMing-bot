from decimal import Decimal, ROUND_DOWN

from src.models import MarketInfo

# Ondo: maintenance margin ≈ notional / (2 × leverage) at max leverage
ONDO_MAINTENANCE_DIVISOR = 2


def align_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    steps = (value / increment).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return steps * increment


def estimate_margin_ratio_pct(
    size: Decimal,
    price: Decimal,
    margin_balance: Decimal,
    leverage: int,
) -> float:
    """Ondo UI margin ratio = totalMaintenanceMargin / marginBalance."""
    if margin_balance <= 0 or size <= 0 or price <= 0:
        return 0.0
    maintenance = (size * price) / Decimal(ONDO_MAINTENANCE_DIVISOR * leverage)
    return float(maintenance / margin_balance * Decimal("100"))


def calc_initial_margin(
    margin_balance: Decimal,
    target_margin_ratio_pct: float,
) -> Decimal:
    """Initial margin needed to reach the Ondo margin ratio target."""
    ratio = Decimal(str(target_margin_ratio_pct)) / Decimal("100")
    maintenance = margin_balance * ratio
    return maintenance * Decimal(ONDO_MAINTENANCE_DIVISOR)


def calc_order_size(
    margin_balance: Decimal,
    price: Decimal,
    target_margin_ratio_pct: float,
    leverage: int,
    market_info: MarketInfo,
    *,
    available_margin: Decimal | None = None,
) -> Decimal:
    """
    Size orders from live margin balance to match Ondo dashboard Margin Ratio.
    Picks the increment (round down or up) closest to the target ratio.
    """
    if price <= 0 or margin_balance <= 0:
        return market_info.base_increment

    ratio = Decimal(str(target_margin_ratio_pct)) / Decimal("100")
    target_maintenance = margin_balance * ratio
    target_notional = target_maintenance * Decimal(ONDO_MAINTENANCE_DIVISOR * leverage)
    raw_size = target_notional / price

    inc = market_info.base_increment
    size_down = max(align_to_increment(raw_size, inc), inc)
    size_up = size_down + inc

    target = float(target_margin_ratio_pct)
    candidates = [size_down]
    if size_up > size_down:
        candidates.append(size_up)

    if available_margin is not None and available_margin > 0:
        max_initial = available_margin * Decimal("0.98")
        max_notional = max_initial * Decimal(leverage)
        max_size = align_to_increment(max_notional / price, inc)
        candidates = [s for s in candidates if calc_initial_margin_for_size(s, price, leverage) <= max_initial]
        if not candidates:
            candidates = [max(max_size, inc)]

    return min(candidates, key=lambda s: abs(estimate_margin_ratio_pct(s, price, margin_balance, leverage) - target))


def calc_initial_margin_for_size(size: Decimal, price: Decimal, leverage: int) -> Decimal:
    return (size * price) / Decimal(leverage)

def calc_order_size_from_initial_margin_pct(
    margin_balance: Decimal,
    price: Decimal,
    initial_margin_pct: float,
    leverage: int,
    market_info: MarketInfo,
    *,
    available_margin: Decimal | None = None,
) -> Decimal:
    """Size from initial margin percent of equity, then apply leverage."""
    if price <= 0 or margin_balance <= 0:
        return market_info.base_increment

    pct = Decimal(str(initial_margin_pct)) / Decimal("100")
    target_initial = margin_balance * pct
    if available_margin is not None and available_margin > 0:
        target_initial = min(target_initial, available_margin * Decimal("0.98"))

    raw_size = (target_initial * Decimal(leverage)) / price
    return max(align_to_increment(raw_size, market_info.base_increment), market_info.base_increment)
