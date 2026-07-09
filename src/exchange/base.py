from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from src.models import Candle, GridLevel, MarginBalance, MarketInfo, MarketSnapshot, Order, Position, Side, Trend


class ExchangeClient(ABC):
    @abstractmethod
    def get_market_info(self, market: str) -> MarketInfo:
        raise NotImplementedError

    @abstractmethod
    def get_market_snapshot(self, market: str) -> MarketSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_balance(self) -> MarginBalance:
        raise NotImplementedError

    @abstractmethod
    def set_leverage(self, market: str, leverage: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_atr_pct(self, market: str, resolution: str = "60", hours: int = 24) -> Optional[float]:
        raise NotImplementedError

    @abstractmethod
    def get_hourly_closes(self, market: str, hours: int = 24) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def get_closes(self, market: str, resolution: str = "15", periods: int = 30) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def get_candles(self, market: str, resolution: str = "15", periods: int = 240) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    def get_book_volumes(self, market: str, depth: int = 5) -> tuple[float, float]:
        """Return (bid_volume, ask_volume) from order book."""
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self, market: str) -> list[Order]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, market: Optional[str] = None) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def place_limit_orders(self, levels: list[GridLevel], size: Decimal, market: str) -> list[Order]:
        raise NotImplementedError

    @abstractmethod
    def close_position_market(self, market: str, side: Side, size: Decimal) -> Order:
        raise NotImplementedError

    @abstractmethod
    def place_reduce_only_limit_order(self, market: str, side: Side, size: Decimal, price: Decimal, client_order_id: str, post_only: bool = True) -> Order:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, market: str, order_id: str) -> Order:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, market: str, order_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancel_grid_orders(self, market: str) -> int:
        raise NotImplementedError


