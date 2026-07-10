import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from src.config import DEFAULT_MAX_LEVERAGE
from src.exchange.base import ExchangeClient
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
    Session,
    Side,
    Trend,
)

logger = logging.getLogger(__name__)

BATCH_LIMIT = 20


class OndoClient(ExchangeClient):
    def __init__(self, base_url: str, key_id: str, api_secret: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.key_id = key_id
        self.api_secret = api_secret
        self.timeout = timeout
        self._session = requests.Session()

    def _sign(self, timestamp: str, method: str, path: str, body: str) -> str:
        payload = timestamp + method.upper() + path + body
        mac = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256)
        return mac.hexdigest()

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        return {
            "ONDO-KEY-ID": self.key_id,
            "ONDO-TIMESTAMP": timestamp,
            "ONDO-SIGN": self._sign(timestamp, method, path, body),
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        auth: bool = True,
    ) -> Any:
        query = ""
        if params:
            query = "?" + urlencode(params)
        full_path = path + query
        url = self.base_url + full_path
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""

        headers = self._headers(method, full_path, body_str) if auth else {}
        response = self._session.request(
            method=method,
            url=url,
            headers=headers,
            data=body_str if body is not None else None,
            timeout=self.timeout,
        )

        try:
            data = response.json()
        except ValueError as exc:
            response.raise_for_status()
            raise RuntimeError(f"Non-JSON response from Ondo API: {response.text}") from exc

        if response.status_code >= 400 or not data.get("success", True):
            error = data.get("error", response.text)
            code = data.get("error_code", "")
            raise RuntimeError(f"Ondo API error ({response.status_code}, {code}): {error}")

        return data.get("result")

    def get_market_info(self, market: str) -> MarketInfo:
        result = self._request("GET", "/v1/markets", auth=False)
        pairs = result["perps"]["tradingPairs"]
        for pair in pairs:
            if pair["market"] == market:
                return MarketInfo(
                    market=market,
                    base_increment=Decimal(pair["baseIncrement"]),
                    quote_increment=Decimal(pair["quoteIncrement"]),
                    max_leverage=DEFAULT_MAX_LEVERAGE.get(market, 20),
                )
        raise ValueError(f"Market not found: {market}")

    def get_market_snapshot(self, market: str) -> MarketSnapshot:
        marks = self._request("GET", "/v1/perps/mark_prices", auth=False)
        mark_data = marks.get(market, {})
        mark = Decimal(mark_data.get("markPrice") or mark_data.get("price", "0"))
        oracle = Decimal(mark_data.get("oraclePrice", mark))

        depth = self._request("GET", "/v1/perps/depth", params={"market": market, "depth": 1}, auth=False)
        best_bid = Decimal(depth["bids"][0][0]) if depth.get("bids") else mark
        best_ask = Decimal(depth["asks"][0][0]) if depth.get("asks") else mark
        mid = (best_bid + best_ask) / 2

        return MarketSnapshot(
            market=market,
            mark_price=mark,
            oracle_price=oracle,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid,
            session=detect_session(),
            trend=Trend.NEUTRAL,
        )

    def get_balance(self) -> MarginBalance:
        result = self._request("GET", "/v1/perps/balance")
        return MarginBalance(
            margin_balance=Decimal(result["marginBalance"]),
            available_margin=Decimal(result["availableMargin"]),
            wallet_balance=Decimal(result["walletBalance"]),
            unrealized_pnl=Decimal(result["unrealizedPnl"]),
            margin_ratio_pct=float(result.get("marginRatio", 0)) * 100,
            used_margin=Decimal(result.get("usedMargin", "0")),
            maintenance_margin=Decimal(result.get("totalMaintenanceMargin", "0")),
        )

    def set_leverage(self, market: str, leverage: int) -> None:
        self._request("POST", "/v1/perps/leverage", body={"market": market, "leverage": str(leverage)})
        logger.info("Set leverage %dx on %s", leverage, market)

    def get_atr_pct(self, market: str, resolution: str = "60", hours: int = 24) -> Optional[float]:
        now = int(time.time())
        start = now - hours * 3600
        result = self._request(
            "GET",
            "/v1/perps/candles",
            params={"market": market, "resolution": resolution, "from": start, "to": now},
        )
        if not result:
            return None
        ranges = []
        for candle in result:
            high, low, close = Decimal(candle["high"]), Decimal(candle["low"]), Decimal(candle["close"])
            if close > 0:
                ranges.append(float((high - low) / close * 100))
        return sum(ranges) / len(ranges) if ranges else None

    def get_hourly_closes(self, market: str, hours: int = 24) -> list[float]:
        return self.get_closes(market, resolution="60", periods=hours)

    def get_closes(self, market: str, resolution: str = "15", periods: int = 30) -> list[float]:
        return [float(c.close) for c in self.get_candles(market, resolution=resolution, periods=periods)]

    def get_candles(self, market: str, resolution: str = "15", periods: int = 240) -> list[Candle]:
        mins = int(resolution) if resolution.isdigit() else 15
        now = int(time.time())
        start = now - periods * mins * 60
        result = self._request(
            "GET",
            "/v1/perps/candles",
            params={"market": market, "resolution": resolution, "from": start, "to": now},
        )
        candles: list[Candle] = []
        for item in result or []:
            close = Decimal(item["close"])
            candles.append(
                Candle(
                    open=Decimal(item.get("open", item.get("o", close))),
                    high=Decimal(item.get("high", item.get("h", close))),
                    low=Decimal(item.get("low", item.get("l", close))),
                    close=close,
                    volume=Decimal(str(item.get("volume", item.get("v", "0")) or "0")),
                )
            )
        return candles

    def get_book_volumes(self, market: str, depth: int = 5) -> tuple[float, float]:
        result = self._request(
            "GET",
            "/v1/perps/depth",
            params={"market": market, "depth": depth},
            auth=False,
        )
        bid_vol = sum(float(b[1]) for b in result.get("bids", []))
        ask_vol = sum(float(a[1]) for a in result.get("asks", []))
        return bid_vol, ask_vol

    def get_open_orders(self, market: str) -> list[Order]:
        result = self._request(
            "GET",
            "/v1/perps/orders",
            params={"market": market, "status": "open", "limit": 1000},
        )
        items = result if isinstance(result, list) else result.get("orders", [])
        return [self._parse_order(item) for item in items]

    def get_positions(self, market: Optional[str] = None) -> list[Position]:
        result = self._request("GET", "/v1/perps/positions")
        positions = []
        for item in result or []:
            if market and item["market"] != market:
                continue
            direction = PositionDirection(item["direction"])
            qty = Decimal(item["netQuantity"])
            if direction == PositionDirection.NEUTRAL or qty == 0:
                continue
            positions.append(
                Position(
                    market=item["market"],
                    direction=direction,
                    net_quantity=qty,
                    average_entry_price=Decimal(item["averageEntryPrice"]),
                    unrealized_pnl=Decimal(item["unrealizedPnl"]),
                    mark_price=Decimal(item["markPrice"]),
                )
            )
        return positions

    def place_limit_orders(self, levels: list[GridLevel], size: Decimal, market: str) -> list[Order]:
        placed: list[Order] = []
        for level in levels:
            body = {
                "side": level.side.value,
                "market": market,
                "price": str(level.price),
                "size": str(size),
                "type": "limit",
                "timeInForce": "GTC",
                "postOnly": True,
                "clientOrderId": level.client_order_id,
            }
            try:
                result = self._request("POST", "/v1/perps/orders", body=body)
                if result:
                    placed.append(self._parse_order(result))
            except RuntimeError as exc:
                logger.warning("Order rejected: %s", exc)
        return placed

    def close_position_market(self, market: str, side: Side, size: Decimal) -> Order:
        result = self._request(
            "POST",
            "/v1/perps/orders",
            body={"side": side.value, "market": market, "size": str(size), "type": "market", "reduceOnly": True},
        )
        return self._parse_order(result)

    def place_reduce_only_limit_order(
        self,
        market: str,
        side: Side,
        size: Decimal,
        price: Decimal,
        client_order_id: str,
        post_only: bool = True,
    ) -> Order:
        result = self._request(
            "POST",
            "/v1/perps/orders",
            body={
                "side": side.value,
                "market": market,
                "price": str(price),
                "size": str(size),
                "type": "limit",
                "timeInForce": "IOC",
                "postOnly": False,
                "reduceOnly": True,
                "clientOrderId": client_order_id,
            },
        )
        return self._parse_order(result)

    def get_order(self, market: str, order_id: str) -> Order:
        result = self._request("GET", f"/v1/perps/orders/{order_id}", params={"market": market})
        return self._parse_order(result)

    def cancel_order(self, market: str, order_id: str) -> None:
        self._request("DELETE", f"/v1/perps/orders/{order_id}", params={"market": market})

    def cancel_grid_orders(self, market: str) -> int:
        cancelled = 0
        for order in self.get_open_orders(market):
            if order.client_order_id and (
                order.client_order_id.startswith("grid_") or order.client_order_id.startswith("single_") or order.client_order_id.startswith("mm_")
            ):
                self._request("DELETE", f"/v1/perps/orders/{order.order_id}", params={"market": market})
                cancelled += 1
        return cancelled

    @staticmethod
    def _parse_order(item: dict[str, Any]) -> Order:
        created_at = None
        if raw := item.get("createdAt"):
            created_at = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        return Order(
            order_id=item["orderId"],
            client_order_id=item.get("clientOrderId"),
            market=item["market"],
            side=Side(item["side"]),
            price=Decimal(item.get("price") or "0"),
            size=Decimal(item["size"]),
            status=item["status"],
            filled_size=Decimal(item.get("filledSize", "0")),
            order_type=OrderType(item.get("type", "limit")),
            created_at=created_at,
        )

