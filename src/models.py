from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class PositionDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Trend(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class Session(str, Enum):
    REGULAR = "regular"
    WEEKEND = "weekend"



@dataclass
class Candle:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

@dataclass
class MarketInfo:
    market: str
    base_increment: Decimal
    quote_increment: Decimal
    max_leverage: int = 20


@dataclass
class MarginBalance:
    margin_balance: Decimal
    available_margin: Decimal
    wallet_balance: Decimal
    unrealized_pnl: Decimal
    margin_ratio_pct: float = 0.0
    used_margin: Decimal = Decimal("0")
    maintenance_margin: Decimal = Decimal("0")


@dataclass
class MarketSnapshot:
    market: str
    mark_price: Decimal
    oracle_price: Decimal
    best_bid: Decimal
    best_ask: Decimal
    mid_price: Decimal
    session: Session
    trend: Trend


@dataclass
class GridLevel:
    price: Decimal
    side: Side
    client_order_id: str


@dataclass
class Order:
    order_id: str
    client_order_id: Optional[str]
    market: str
    side: Side
    price: Decimal
    size: Decimal
    status: str
    filled_size: Decimal
    order_type: OrderType
    created_at: Optional[float] = None


@dataclass
class Position:
    market: str
    direction: PositionDirection
    net_quantity: Decimal
    average_entry_price: Decimal
    unrealized_pnl: Decimal
    mark_price: Decimal

    @property
    def notional_value(self) -> Decimal:
        return self.net_quantity * self.mark_price
