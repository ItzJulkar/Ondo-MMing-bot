import logging
import random
import uuid
from decimal import Decimal
from typing import Optional

from src.grid.regime import detect_session
from src.models import (
    Candle,
    GridLevel,
    MarginBalance,
    MarketInfo,
    MarketSnapshot,
    Order,
    OrderType,
    Position,
    PositionDirection,
    Side,
    Trend,
)
from src.exchange.base import ExchangeClient

logger = logging.getLogger(__name__)

MOCK_PRICES = {
    "XAU-USD.P": Decimal("2650.00"),
    "XAG-USD.P": Decimal("31.50"),
    "WTI-USD.P": Decimal("82.00"),
    "BTC-USD.P": Decimal("60000.00"),
}


class MockOndoClient(ExchangeClient):
    def __init__(self, markets: list[str], margin_balance: Decimal = Decimal("5000")):
        self.markets = markets
        self._margin_balance = margin_balance
        self._prices = {m: MOCK_PRICES.get(m, Decimal("100")) for m in markets}
        self._orders: dict[str, Order] = {}
        self._positions: list[Position] = []
        self._market_info = {
            m: MarketInfo(
                market=m,
                base_increment=Decimal("0.0001") if "BTC" in m else Decimal("0.01"),
                quote_increment=Decimal("0.1") if "BTC" in m else Decimal("0.01"),
                max_leverage=20,
            )
            for m in markets
        }
        self._trend_bias = {m: 0.0 for m in markets}

    def get_market_info(self, market: str) -> MarketInfo:
        return self._market_info[market]

    def get_market_snapshot(self, market: str) -> MarketSnapshot:
        self._tick_price(market)
        price = self._prices[market]
        spread = price * Decimal("0.0002")
        return MarketSnapshot(
            market=market,
            mark_price=price,
            oracle_price=price,
            best_bid=price - spread,
            best_ask=price + spread,
            mid_price=price,
            session=detect_session(),
            trend=Trend.NEUTRAL,
        )

    def get_balance(self) -> MarginBalance:
        self._update_position_pnl()
        total_upnl = sum(p.unrealized_pnl for p in self._positions)
        margin = self._margin_balance + total_upnl
        return MarginBalance(
            margin_balance=margin,
            available_margin=max(Decimal("0"), margin * Decimal("0.7")),
            wallet_balance=self._margin_balance,
            unrealized_pnl=total_upnl,
        )

    def set_leverage(self, market: str, leverage: int) -> None:
        logger.info("[DRY-RUN] Set leverage %dx on %s", leverage, market)

    def get_atr_pct(self, market: str, resolution: str = "60", hours: int = 24) -> Optional[float]:
        return 0.18 if "XAU" in market else 0.35

    def get_hourly_closes(self, market: str, hours: int = 24) -> list[float]:
        return self.get_closes(market, "60", hours)

    def get_closes(self, market: str, resolution: str = "15", periods: int = 30) -> list[float]:
        return [float(c.close) for c in self.get_candles(market, resolution=resolution, periods=periods)]

    def get_candles(self, market: str, resolution: str = "15", periods: int = 240) -> list[Candle]:
        base = self._prices[market]
        scale = self._price_scale(market)
        candles: list[Candle] = []
        price = base
        for _ in range(periods):
            drift = Decimal(str(random.uniform(-float(scale), float(scale))))
            open_price = price
            close = max(Decimal("1"), price + drift)
            wick = abs(Decimal(str(random.uniform(0, float(scale)))))
            high = max(open_price, close) + wick
            low = max(Decimal("1"), min(open_price, close) - wick)
            candles.append(
                Candle(
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=Decimal(str(random.uniform(50, 500))),
                )
            )
            price = close
        return candles

    def get_book_volumes(self, market: str, depth: int = 5) -> tuple[float, float]:
        return (100.0 + random.uniform(-20, 20), 100.0 + random.uniform(-20, 20))

    def get_open_orders(self, market: str) -> list[Order]:
        self._maybe_fill_orders(market)
        return [o for o in self._orders.values() if o.status == "open" and o.market == market]

    def get_positions(self, market: Optional[str] = None) -> list[Position]:
        self._update_position_pnl()
        if market:
            return [p for p in self._positions if p.market == market]
        return list(self._positions)

    def place_limit_orders(self, levels: list[GridLevel], size: Decimal, market: str) -> list[Order]:
        placed = []
        for level in levels:
            order = Order(
                order_id=uuid.uuid4().hex,
                client_order_id=level.client_order_id,
                market=market,
                side=level.side,
                price=level.price,
                size=size,
                status="open",
                filled_size=Decimal("0"),
                order_type=OrderType.LIMIT,
            )
            self._orders[order.order_id] = order
            placed.append(order)
            logger.info("[DRY-RUN] Maker %s %s %s @ %s", market, level.side.value, size, level.price)
        return placed

    def close_position_market(self, market: str, side: Side, size: Decimal) -> Order:
        closed_pnl = Decimal("0")
        remaining = []
        for pos in self._positions:
            if pos.market != market:
                remaining.append(pos)
            else:
                closed_pnl += pos.unrealized_pnl
        self._positions = remaining
        self._margin_balance += closed_pnl
        logger.info("[DRY-RUN] Taker close %s %s %s", market, side.value, size)
        return Order(
            order_id=uuid.uuid4().hex,
            client_order_id=None,
            market=market,
            side=side,
            price=self._prices[market],
            size=size,
            status="fullyfilled",
            filled_size=size,
            order_type=OrderType.MARKET,
        )

    def place_reduce_only_limit_order(
        self,
        market: str,
        side: Side,
        size: Decimal,
        price: Decimal,
        client_order_id: str,
        post_only: bool = True,
    ) -> Order:
        order = Order(
            order_id=uuid.uuid4().hex,
            client_order_id=client_order_id,
            market=market,
            side=side,
            price=price,
            size=size,
            status="open",
            filled_size=Decimal("0"),
            order_type=OrderType.LIMIT,
        )
        self._orders[order.order_id] = order
        logger.info("[DRY-RUN] Reduce-only maker close %s %s %s @ %s", market, side.value, size, price)
        return order

    def get_order(self, market: str, order_id: str) -> Order:
        if order_id in self._orders:
            return self._orders[order_id]
        raise KeyError(order_id)

    def cancel_order(self, market: str, order_id: str) -> None:
        if order_id in self._orders:
            self._orders[order_id].status = "canceled"

    def cancel_grid_orders(self, market: str) -> int:
        n = 0
        for oid, order in list(self._orders.items()):
            if order.market == market and order.client_order_id and (
                order.client_order_id.startswith("grid_") or order.client_order_id.startswith("single_") or order.client_order_id.startswith("mm_")
            ):
                order.status = "canceled"
                n += 1
        return n

    def _price_scale(self, market: str) -> Decimal:
        if "BTC" in market:
            return Decimal("80")
        if "XAU" in market:
            return Decimal("2.0")
        if "WTI" in market:
            return Decimal("0.12")
        return Decimal("0.05")

    def _tick_price(self, market: str) -> None:
        scale = self._price_scale(market)
        drift = Decimal(str(random.uniform(-float(scale), float(scale))))
        self._prices[market] = max(Decimal("1"), self._prices[market] + drift)

    def _maybe_fill_orders(self, market: str) -> None:
        price = self._prices[market]
        for order in list(self._orders.values()):
            if order.status != "open" or order.market != market:
                continue
            filled = (order.side == Side.BUY and price <= order.price) or (
                order.side == Side.SELL and price >= order.price
            )
            if not filled:
                continue
            order.status = "fullyfilled"
            order.filled_size = order.size
            if order.client_order_id and order.client_order_id.startswith("mm_close_"):
                closed_pnl = Decimal("0")
                remaining = []
                for pos in self._positions:
                    if pos.market != order.market:
                        remaining.append(pos)
                    else:
                        closed_pnl += pos.unrealized_pnl
                self._positions = remaining
                self._margin_balance += closed_pnl
                logger.info("[DRY-RUN] Filled reduce-only close %s %s @ %s", market, order.side.value, order.price)
                continue

            direction = PositionDirection.LONG if order.side == Side.BUY else PositionDirection.SHORT
            self._positions.append(
                Position(
                    market=order.market,
                    direction=direction,
                    net_quantity=order.size,
                    average_entry_price=order.price,
                    unrealized_pnl=Decimal("0"),
                    mark_price=price,
                )
            )
            logger.info("[DRY-RUN] Filled %s %s @ %s", market, order.side.value, order.price)

    def _update_position_pnl(self) -> None:
        updated = []
        for pos in self._positions:
            price = self._prices[pos.market]
            if pos.direction == PositionDirection.LONG:
                pnl = (price - pos.average_entry_price) * pos.net_quantity
            else:
                pnl = (pos.average_entry_price - price) * pos.net_quantity
            updated.append(
                Position(
                    market=pos.market,
                    direction=pos.direction,
                    net_quantity=pos.net_quantity,
                    average_entry_price=pos.average_entry_price,
                    unrealized_pnl=pnl,
                    mark_price=price,
                )
            )
        self._positions = updated



