import logging
from decimal import Decimal

from src.config import AppConfig
from src.exchange.base import ExchangeClient
from src.grid.placement import build_smart_grid, needs_rebalance
from src.grid.regime import detect_trend, level_split, session_levels_adjustment
from src.models import GridLevel, MarketSnapshot, Order
from src.risk.sizing import calc_order_size
from src.risk.spacing import compute_grid_spacing_pct, compute_levels_per_side

logger = logging.getLogger(__name__)


class GridStrategy:
    def __init__(self, config: AppConfig, exchange: ExchangeClient, market: str):
        self.config = config
        self.exchange = exchange
        self.market = market
        self._market_info = exchange.get_market_info(market)
        self._anchor_price: Decimal | None = None

    def _snapshot(self) -> MarketSnapshot:
        snap = self.exchange.get_market_snapshot(self.market)
        closes = self.exchange.get_hourly_closes(self.market)
        snap.trend = detect_trend(closes)
        return snap

    def _min_order_margin(self, price: Decimal) -> Decimal:
        min_size = self._market_info.base_increment
        notional = min_size * price
        return notional / Decimal(self.config.max_leverage_for(self.market))

    def should_trade(
        self,
        snapshot: MarketSnapshot,
        margin_balance: Decimal,
        available_margin: Decimal,
    ) -> tuple[bool, str]:
        min_margin = self._min_order_margin(snapshot.mark_price)
        from src.risk.sizing import calc_initial_margin

        per_order_margin = calc_initial_margin(margin_balance, self.config.margin.target_margin_ratio_pct)

        if available_margin < min_margin:
            return False, f"insufficient margin (need ~${min_margin:.2f}, have ${available_margin:.2f})"
        if per_order_margin < min_margin:
            return False, f"order margin ${per_order_margin:.2f} below min ${min_margin:.2f} — deposit more USDC"
        return True, "ok"

    def resolve_order_size(self, margin_balance: Decimal, price: Decimal) -> Decimal:
        if self.config.grid.order_size:
            return Decimal(self.config.grid.order_size)
        return calc_order_size(
            margin_balance=margin_balance,
            price=price,
            target_margin_ratio_pct=self.config.margin.target_margin_ratio_pct,
            leverage=self.config.max_leverage_for(self.market),
            market_info=self._market_info,
        )

    def resolve_params(self, snapshot: MarketSnapshot, margin_balance: Decimal) -> dict:
        atr = self.exchange.get_atr_pct(self.market)
        spacing = (
            float(self.config.grid.spacing_pct)
            if self.config.grid.spacing_pct is not None
            else compute_grid_spacing_pct(self.config, self.market, atr, snapshot.session)
        )
        base_levels = compute_levels_per_side(self.config, margin_balance, len(self.config.markets))
        levels = session_levels_adjustment(snapshot.session, base_levels)
        buy_lv, sell_lv = level_split(levels, snapshot.trend)
        size = self.resolve_order_size(margin_balance, snapshot.mark_price)

        return {
            "spacing": spacing,
            "buy_levels": buy_lv,
            "sell_levels": sell_lv,
            "size": size,
            "trend": snapshot.trend.value,
            "session": snapshot.session.value,
        }

    def compute_levels(self, snapshot: MarketSnapshot, margin_balance: Decimal) -> list[GridLevel]:
        params = self.resolve_params(snapshot, margin_balance)
        return build_smart_grid(
            snapshot=snapshot,
            market_info=self._market_info,
            buy_levels=params["buy_levels"],
            sell_levels=params["sell_levels"],
            spacing_pct=params["spacing"],
        )

    def sync_grid_orders(self, margin_balance: Decimal, available_margin: Decimal) -> list[Order]:
        snapshot = self._snapshot()
        params = self.resolve_params(snapshot, margin_balance)

        can_trade, reason = self.should_trade(snapshot, margin_balance, available_margin)
        if not can_trade:
            logger.warning("[%s] Skipping grid placement: %s", self.market, reason)
            return []

        logger.info(
            "[%s] %s session | %s trend | mark=$%s | size=%s | spacing=%.4f%% | buys=%d sells=%d",
            self.market,
            params["session"],
            params["trend"],
            snapshot.mark_price,
            params["size"],
            params["spacing"],
            params["buy_levels"],
            params["sell_levels"],
        )

        if needs_rebalance(self._anchor_price or Decimal("0"), snapshot.mark_price, params["spacing"]):
            cancelled = self.exchange.cancel_grid_orders(self.market)
            if cancelled:
                logger.info("[%s] Rebalanced: cancelled %d stale grid orders (price drift)", self.market, cancelled)
            self._anchor_price = snapshot.mark_price

        target_levels = self.compute_levels(snapshot, margin_balance)
        open_orders = self.exchange.get_open_orders(self.market)
        existing_ids = {
            o.client_order_id
            for o in open_orders
            if o.client_order_id and o.client_order_id.startswith("grid_")
        }

        missing = [lv for lv in target_levels if lv.client_order_id not in existing_ids]
        if not missing:
            logger.debug("[%s] Grid in sync (%d orders)", self.market, len(existing_ids))
            return []

        placed = self.exchange.place_limit_orders(missing, params["size"], self.market)
        if placed and self._anchor_price is None:
            self._anchor_price = snapshot.mark_price
        logger.info("[%s] Placed %d maker limit orders", self.market, len(placed))
        return placed