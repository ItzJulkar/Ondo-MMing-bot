import logging
from decimal import Decimal

from src.config import AppConfig
from src.exchange.base import ExchangeClient
from src.models import Position, Side

logger = logging.getLogger(__name__)


class PnlMonitor:
    def __init__(self, config: AppConfig, exchange: ExchangeClient):
        self.config = config
        self.exchange = exchange

    def _initial_margin(self, position: Position) -> Decimal:
        leverage = Decimal(self.config.max_leverage_for(position.market))
        entry_notional = abs(position.net_quantity) * position.average_entry_price
        if leverage <= 0:
            return Decimal("0")
        return entry_notional / leverage

    def _roi_pct(self, position: Position) -> Decimal:
        initial_margin = self._initial_margin(position)
        if initial_margin <= 0:
            return Decimal("0")
        return position.unrealized_pnl / initial_margin * Decimal("100")

    @staticmethod
    def close_side(position: Position) -> Side:
        if position.direction.value == "long":
            return Side.SELL
        return Side.BUY

    def _expected_close_slippage_pct(self, position: Position) -> Decimal:
        snapshot = self.exchange.get_market_snapshot(position.market)
        reference = position.mark_price if position.mark_price > 0 else snapshot.mark_price
        if reference <= 0:
            return Decimal("0")

        side = self.close_side(position)
        expected_exit = snapshot.best_bid if side == Side.SELL else snapshot.best_ask
        return abs(expected_exit - reference) / reference * Decimal("100")

    def _slippage_allows_close(self, position: Position, reason: str) -> bool:
        max_slippage = Decimal(str(self.config.pnl.max_close_slippage_pct))
        slippage = self._expected_close_slippage_pct(position)
        if slippage <= max_slippage:
            return True

        if reason == "stop_loss" and not self.config.pnl.enforce_slippage_on_stop_loss:
            logger.warning(
                "[%s] SL close slippage %.4f%% > max %.4f%%; closing anyway to control loss",
                position.market,
                float(slippage),
                float(max_slippage),
            )
            return True

        logger.info(
            "[%s] %s ready but waiting: expected close slippage %.4f%% > max %.4f%%",
            position.market,
            reason,
            float(slippage),
            float(max_slippage),
        )
        return False

    def positions_to_close(self, market: str, margin_balance: Decimal) -> list[tuple[Position, str]]:
        actions: list[tuple[Position, str]] = []
        tp_pct = Decimal(str(self.config.pnl.take_profit_roi_pct))
        sl_pct = Decimal(str(self.config.pnl.stop_loss_roi_pct))

        for position in self.exchange.get_positions(market):
            roi_pct = self._roi_pct(position)
            initial_margin = self._initial_margin(position)

            if roi_pct >= tp_pct:
                if not self._slippage_allows_close(position, "take_profit"):
                    continue
                actions.append((position, "take_profit"))
                logger.info(
                    "[%s] TP: ROI %.2f%% >= %.2f%% | uPnL $%s | initial margin ~$%s",
                    market,
                    float(roi_pct),
                    float(tp_pct),
                    round(position.unrealized_pnl, 6),
                    round(initial_margin, 6),
                )
            elif roi_pct <= -sl_pct:
                if not self._slippage_allows_close(position, "stop_loss"):
                    continue
                actions.append((position, "stop_loss"))
                logger.info(
                    "[%s] SL: ROI %.2f%% <= -%.2f%% | uPnL $%s | initial margin ~$%s",
                    market,
                    float(roi_pct),
                    float(sl_pct),
                    round(position.unrealized_pnl, 6),
                    round(initial_margin, 6),
                )
        return actions

    def close_positions(self, market: str, margin_balance: Decimal) -> int:
        closed = 0
        for position, reason in self.positions_to_close(market, margin_balance):
            side = self.close_side(position)
            self.exchange.close_position_market(market, side, position.net_quantity)
            logger.info(
                "[%s] Closed %s via taker/reduceOnly (%s): size=%s",
                market,
                position.direction.value,
                reason,
                position.net_quantity,
            )
            closed += 1
        return closed
