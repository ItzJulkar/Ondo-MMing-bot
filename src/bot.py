import logging
import signal
import time

from src.config import AppConfig
from src.daemon import clear_pid, clear_safe_exit, safe_exit_requested, stop_requested
from src.exchange.base import ExchangeClient
from src.strategy.single_maker import SingleMakerStrategy

logger = logging.getLogger(__name__)


class GridBot:
    def __init__(self, config: AppConfig, exchange: ExchangeClient):
        self.config = config
        self.exchange = exchange
        self.strategy = SingleMakerStrategy(config, exchange)
        self._running = False

    def _setup_leverage(self) -> None:
        for market in self.config.markets:
            max_lev = self.config.max_leverage_for(market)
            try:
                self.exchange.set_leverage(market, max_lev)
            except Exception:
                logger.exception("Failed to set leverage on %s", market)

    def _cancel_stale_grid_orders(self) -> None:
        for market in self.config.markets:
            n = self.exchange.cancel_grid_orders(market)
            if n:
                logger.info("[%s] Cancelled %d old grid orders", market, n)

    def run(self) -> None:
        self._running = True
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        mode = "DRY-RUN" if self.config.bot.dry_run else "LIVE"
        logger.info(
            "Market-maker bot [%s] | entryTTL=%ds closeReprice=%.0fs | spread %.3f%%-%.3f%% | limit-only close",
            mode,
            self.strategy._timeout,
            self.config.close_reprice_sec,
            self.config.min_spread_pct,
            self.config.max_spread_pct,
        )

        if not self.config.bot.dry_run:
            self._setup_leverage()
            self._cancel_stale_grid_orders()

        safe_exit_logged = False
        while self._running:
            if stop_requested():
                logger.info("Stop command received — shutting down")
                self._running = False
                break

            safe_exit = safe_exit_requested()
            if safe_exit and not safe_exit_logged:
                logger.info("Safe exit requested — no new entries; managing existing closes only")
                safe_exit_logged = True

            try:
                self.strategy.tick(allow_new_entries=not safe_exit)
                if safe_exit and self.strategy.is_flat():
                    logger.info("Safe exit complete — no bot positions or open bot orders remain")
                    self._running = False
                    break
            except Exception:
                logger.exception("Bot tick failed")
            time.sleep(self.config.bot.poll_interval_sec)

        clear_pid()
        clear_safe_exit()
        logger.info("Bot stopped")

    def _handle_stop(self, signum, frame) -> None:
        logger.info("Shutdown signal received (%s)", signum)
        self._running = False
