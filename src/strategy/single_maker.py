import logging
import time
import uuid
from decimal import Decimal, ROUND_CEILING

from src.config import AppConfig
from src.exchange.base import ExchangeClient
from src.grid.levels import align_price
from src.models import GridLevel, MarketSnapshot, Order, Position, PositionDirection, Side
from src.risk.sizing import calc_initial_margin_for_size, calc_order_size_from_initial_margin_pct, estimate_margin_ratio_pct

logger = logging.getLogger(__name__)


class SingleMakerStrategy:
    """
    Paired maker strategy:
    1. Place two post-only maker orders together: buy at book bid and sell 0.015% above it.
    2. Whichever side fills first becomes inventory; the opposite order is kept as the close.
    3. First pair uses the normal target spread; loss-side inventory waits at the smaller loss close spread.
    4. If inventory is in profit, the close is re-quoted at current book maker price after close_reprice_sec.
    5. Every order in this mode is post-only maker; no market/taker close is used.
    """

    ENTRY_PREFIX = "mm_entry_"
    CLOSE_PREFIX = "mm_close_"
    FAST_CLOSE_PREFIX = "mm_close_fast_"

    def __init__(self, config: AppConfig, exchange: ExchangeClient):
        self.config = config
        self.exchange = exchange
        self._timeout = config.maker_timeout_sec
        self._placed_at: dict[str, float] = {}

    @staticmethod
    def _pct_diff(value: Decimal, reference: Decimal) -> Decimal:
        if reference <= 0:
            return Decimal("0")
        return abs(value - reference) / reference * Decimal("100")

    @staticmethod
    def _spread_pct(snapshot: MarketSnapshot) -> Decimal:
        mid = (snapshot.best_bid + snapshot.best_ask) / Decimal("2")
        if mid <= 0:
            return Decimal("0")
        return (snapshot.best_ask - snapshot.best_bid) / mid * Decimal("100")

    def _target_pct(self) -> Decimal:
        return Decimal(str(self.config.min_round_trip_profit_pct)) / Decimal("100")

    def _loss_target_pct(self) -> Decimal:
        return Decimal(str(self.config.loss_close_profit_pct)) / Decimal("100")

    @staticmethod
    def _ceil_price(price: Decimal, increment: Decimal) -> Decimal:
        if increment <= 0:
            return price
        steps = (price / increment).quantize(Decimal("1"), rounding=ROUND_CEILING)
        return steps * increment

    def _target_close_price(self, position: Position, target_pct: Decimal) -> Decimal:
        info = self.exchange.get_market_info(position.market)
        inc = info.quote_increment
        if self._close_side(position) == Side.SELL:
            raw = position.average_entry_price * (Decimal("1") + target_pct)
            return self._ceil_price(raw, inc)
        raw = position.average_entry_price * (Decimal("1") - target_pct)
        return max(align_price(raw, inc), inc)

    def _close_price_for_roi(self, position: Position, snapshot: MarketSnapshot) -> tuple[Side, Decimal, str]:
        info = self.exchange.get_market_info(position.market)
        inc = info.quote_increment
        side = self._close_side(position)
        roi = self._roi_pct(position)
        if roi <= 0:
            return side, self._target_close_price(position, self._loss_target_pct()), "loss-target"
        if side == Side.SELL:
            return side, align_price(snapshot.best_ask, inc), "profit-follow"
        return side, max(align_price(snapshot.best_bid, inc), inc), "profit-follow"

    def _close_order_matches_loss_target(self, position: Position, order: Order) -> bool:
        return order.price == self._target_close_price(position, self._loss_target_pct())

    def _initial_margin(self, position: Position) -> Decimal:
        leverage = Decimal(self.config.max_leverage_for(position.market))
        if leverage <= 0:
            return Decimal("0")
        return abs(position.net_quantity) * position.average_entry_price / leverage

    def _roi_pct(self, position: Position) -> Decimal:
        initial_margin = self._initial_margin(position)
        if initial_margin <= 0:
            return Decimal("0")
        return position.unrealized_pnl / initial_margin * Decimal("100")


    def _market_is_safe(self, snapshot: MarketSnapshot) -> bool:
        if snapshot.mark_price <= 0 or snapshot.best_bid <= 0 or snapshot.best_ask <= 0:
            logger.warning("[%s] Skipping: bad market snapshot", snapshot.market)
            return False
        if snapshot.best_ask <= snapshot.best_bid:
            logger.warning("[%s] Skipping: crossed/locked book", snapshot.market)
            return False

        spread_pct = self._spread_pct(snapshot)
        min_spread = Decimal(str(self.config.min_spread_pct))
        max_spread = Decimal(str(self.config.max_spread_pct))
        if spread_pct < min_spread:
            logger.info("[%s] MM skip: spread %.4f%% < min %.4f%%", snapshot.market, float(spread_pct), float(min_spread))
            return False
        if spread_pct > max_spread:
            logger.info("[%s] MM skip: spread %.4f%% > max %.4f%%", snapshot.market, float(spread_pct), float(max_spread))
            return False

        max_mark_oracle_diff = Decimal(str(self.config.max_mark_oracle_diff_pct))
        mark_oracle_diff = self._pct_diff(snapshot.mark_price, snapshot.oracle_price)
        if snapshot.oracle_price > 0 and mark_oracle_diff > max_mark_oracle_diff:
            logger.info(
                "[%s] MM skip: mark/oracle diff %.4f%% > max %.4f%%",
                snapshot.market,
                float(mark_oracle_diff),
                float(max_mark_oracle_diff),
            )
            return False
        return True

    def _bot_open_orders(self, market: str | None = None) -> list[Order]:
        orders: list[Order] = []
        markets = [market] if market else self.config.markets
        for m in markets:
            for order in self.exchange.get_open_orders(m):
                if order.client_order_id and order.client_order_id.startswith("mm_"):
                    orders.append(order)
        return orders

    def _positions_by_market(self) -> dict[str, list[Position]]:
        return {market: self.exchange.get_positions(market) for market in self.config.markets}

    def _active_markets(self) -> set[str]:
        active: set[str] = set()
        for market, positions in self._positions_by_market().items():
            if positions:
                active.add(market)
        for order in self._bot_open_orders():
            active.add(order.market)
        return active

    def _order_age(self, order: Order) -> float:
        if order.created_at:
            return time.time() - order.created_at
        return time.time() - self._placed_at.get(order.order_id, time.time())

    def _cancel_order(self, order: Order, reason: str) -> None:
        self.exchange.cancel_order(order.market, order.order_id)
        self._placed_at.pop(order.order_id, None)
        logger.info("[%s] Cancelled %s %s (%s)", order.market, order.client_order_id, order.order_id, reason)

    def _cancel_orders(self, orders: list[Order], reason: str) -> None:
        for order in orders:
            self._cancel_order(order, reason)

    def _cancel_idle_orders_for_safe_exit(self) -> None:
        """Safe exit keeps only close orders for existing positions."""
        for market in self.config.markets:
            positions = self.exchange.get_positions(market)
            orders = self._bot_open_orders(market)
            if not orders:
                continue

            if not positions:
                self._cancel_orders(orders, "safe exit; no position, cancel idle entry")
                continue

            close_side = self._close_side(positions[0])
            wrong_side_orders = [order for order in orders if order.side != close_side]
            if wrong_side_orders:
                self._cancel_orders(wrong_side_orders, "safe exit; keep close side only")

    def is_flat(self) -> bool:
        for market in self.config.markets:
            if self.exchange.get_positions(market):
                return False
            if self._bot_open_orders(market):
                return False
        return True

    @staticmethod
    def _close_side(position: Position) -> Side:
        return Side.SELL if position.direction == PositionDirection.LONG else Side.BUY

    def _paired_prices(self, snapshot: MarketSnapshot) -> tuple[Decimal, Decimal]:
        info = self.exchange.get_market_info(snapshot.market)
        inc = info.quote_increment
        buy_price = align_price(snapshot.best_bid, inc)
        if buy_price <= 0:
            buy_price = align_price(snapshot.mark_price, inc)
        target_sell = buy_price * (Decimal("1") + self._target_pct())
        sell_price = align_price(max(target_sell, snapshot.best_ask), inc)
        if sell_price <= snapshot.best_bid:
            sell_price = align_price(snapshot.best_ask, inc)
        if sell_price <= buy_price:
            sell_price = buy_price + inc
        return buy_price, sell_price

    def _maker_close_price(self, position: Position, snapshot: MarketSnapshot) -> tuple[Side, Decimal, str]:
        return self._close_price_for_roi(position, snapshot)

    def _handle_order_fills_and_stale(self) -> None:
        for order in list(self._bot_open_orders()):
            try:
                fresh = self.exchange.get_order(order.market, order.order_id)
            except Exception:
                self._placed_at.pop(order.order_id, None)
                continue

            if fresh.status == "fullyfilled":
                logger.info("[%s] Filled %s %s @ %s", fresh.market, fresh.client_order_id, fresh.side.value, fresh.price)
                self._placed_at.pop(fresh.order_id, None)
                continue
            if fresh.status == "canceled":
                self._placed_at.pop(fresh.order_id, None)
                continue
            if fresh.filled_size > 0:
                self._cancel_order(fresh, "partial fill; avoid stale inventory")
                continue

            positions = self.exchange.get_positions(fresh.market)
            ttl = self._timeout
            is_close = bool(positions and fresh.side == self._close_side(positions[0]))
            if is_close:
                position = positions[0]
                if self._roi_pct(position) <= 0:
                    if not self._close_order_matches_loss_target(position, fresh):
                        self._cancel_order(fresh, "loss close retarget to 0.005%")
                    continue
                ttl = self.config.close_reprice_sec
            if self._order_age(fresh) >= ttl:
                reason = "profitable stale close quote" if is_close else "stale pair quote"
                self._cancel_order(fresh, reason)

    def _manage_inventory(self) -> None:
        for market in self.config.markets:
            positions = self.exchange.get_positions(market)
            orders = self._bot_open_orders(market)

            if not positions:
                continue

            snapshot = self.exchange.get_market_snapshot(market)
            position = positions[0]
            close_side = self._close_side(position)
            close_orders = [o for o in orders if o.side == close_side]
            wrong_side_orders = [o for o in orders if o.side != close_side]

            if wrong_side_orders:
                self._cancel_orders(wrong_side_orders, "position exists; wrong side")

            if close_orders:
                continue

            side, price, mode = self._maker_close_price(position, snapshot)
            cid = f"{self.CLOSE_PREFIX}{market.replace('-', '_').replace('.', '_')}_{uuid.uuid4().hex[:10]}"
            placed = self.exchange.place_limit_orders([GridLevel(price, side, cid)], position.net_quantity, market)
            for order in placed:
                self._placed_at[order.order_id] = time.time()
            if placed:
                logger.info(
                    "[%s] Re-quoted maker close %s %s @ %s | ROI %.2f%% | entry=%s | mode=%s",
                    market,
                    side.value,
                    position.net_quantity,
                    price,
                    float(self._roi_pct(position)),
                    position.average_entry_price,
                )

    def _place_entry_quotes(self, balance) -> None:
        active_markets = self._active_markets()
        slots = self.config.max_active_trades - len(active_markets)
        if slots <= 0:
            return

        for market in self.config.markets:
            if slots <= 0:
                break
            if market in active_markets:
                continue
            if self.exchange.get_positions(market) or self._bot_open_orders(market):
                continue

            snapshot = self.exchange.get_market_snapshot(market)
            if not self._market_is_safe(snapshot):
                continue

            info = self.exchange.get_market_info(market)
            leverage = self.config.max_leverage_for(market)
            size = calc_order_size_from_initial_margin_pct(
                balance.margin_balance,
                snapshot.mark_price,
                self.config.margin.per_trade_initial_margin_pct,
                leverage,
                info,
                available_margin=balance.available_margin,
            )
            initial_margin = calc_initial_margin_for_size(size, snapshot.mark_price, leverage)
            if balance.available_margin < initial_margin:
                logger.warning(
                    "[%s] MM skip: not enough margin (available $%s, need ~$%s)",
                    market,
                    round(balance.available_margin, 4),
                    round(initial_margin, 4),
                )
                continue

            buy_price, sell_price = self._paired_prices(snapshot)
            uid = uuid.uuid4().hex[:10]
            levels = [
                GridLevel(buy_price, Side.BUY, f"{self.ENTRY_PREFIX}{market.replace('-', '_').replace('.', '_')}_buy_{uid}"),
                GridLevel(sell_price, Side.SELL, f"{self.CLOSE_PREFIX}{market.replace('-', '_').replace('.', '_')}_sell_{uid}"),
            ]
            placed = self.exchange.place_limit_orders(levels, size, market)
            for order in placed:
                self._placed_at[order.order_id] = time.time()
            if placed:
                est_ratio = estimate_margin_ratio_pct(size, snapshot.mark_price, balance.margin_balance, leverage)
                logger.info(
                    "[%s] Paired maker buy %s / sell %s size=%s | target %.4f%% | initial margin ~$%s (%.1f%% equity) | est. margin ratio %.2f%%",
                    market,
                    buy_price,
                    sell_price,
                    size,
                    float(Decimal(str(self.config.min_round_trip_profit_pct))),
                    round(initial_margin, 4),
                    self.config.margin.per_trade_initial_margin_pct,
                    est_ratio,
                )
                slots -= 1

    def tick(self, allow_new_entries: bool = True) -> None:
        self._handle_order_fills_and_stale()
        if not allow_new_entries:
            self._cancel_idle_orders_for_safe_exit()
        self._manage_inventory()
        if allow_new_entries:
            balance = self.exchange.get_balance()
            self._place_entry_quotes(balance)

