"""Indicator scoring for Ondo maker entries.

Long setup:
- price above EMA50
- EMA50 above EMA200
- bounce from VWAP, MA15, or recent support
- RSI crosses/rises above 50
- MACD bullish crossover

Short setup mirrors those rules.
"""

from dataclasses import dataclass
from enum import Enum

from src.models import Candle, Side


class SignalBias(str, Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"


@dataclass
class SignalResult:
    side: Side | None
    score: int
    reason: str


def _closes(candles: list[Candle]) -> list[float]:
    return [float(c.close) for c in candles]


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * alpha) + (out[-1] * (1.0 - alpha)))
    return out


def rsi_series(values: list[float], period: int = 14) -> list[float]:
    if len(values) < period + 1:
        return [50.0 for _ in values]

    rsis = [50.0] * period
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(values) + 1):
        if i > period + 1:
            diff = values[i - 1] - values[i - 2]
            avg_gain = ((avg_gain * (period - 1)) + max(diff, 0.0)) / period
            avg_loss = ((avg_loss * (period - 1)) + max(-diff, 0.0)) / period
        if avg_loss == 0:
            rsis.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100.0 - (100.0 / (1.0 + rs)))
    return rsis[-len(values):]


def macd(values: list[float]) -> tuple[list[float], list[float]]:
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    line = [f - s for f, s in zip(fast, slow)]
    signal = ema_series(line, 9)
    return line, signal


def vwap(candles: list[Candle], period: int = 50) -> float | None:
    recent = candles[-period:]
    if not recent:
        return None
    weighted = 0.0
    total_volume = 0.0
    typical_prices = []
    for candle in recent:
        typical = float((candle.high + candle.low + candle.close) / 3)
        volume = float(candle.volume)
        typical_prices.append(typical)
        if volume > 0:
            weighted += typical * volume
            total_volume += volume
    if total_volume > 0:
        return weighted / total_volume
    return sum(typical_prices) / len(typical_prices)


def _crossed_above(previous_a: float, current_a: float, previous_b: float, current_b: float) -> bool:
    return previous_a <= previous_b and current_a > current_b


def _crossed_below(previous_a: float, current_a: float, previous_b: float, current_b: float) -> bool:
    return previous_a >= previous_b and current_a < current_b


def _bounce_or_reject(candles: list[Candle], direction: SignalBias) -> tuple[bool, str]:
    values = _closes(candles)
    ma15 = sma(values, 15)
    vw = vwap(candles, 50)
    if len(candles) < 25 or ma15 is None or vw is None:
        return False, "no bounce data"

    last = candles[-1]
    close = float(last.close)
    low = float(last.low)
    high = float(last.high)
    recent = candles[-25:-1]
    support = min(float(c.low) for c in recent)
    resistance = max(float(c.high) for c in recent)
    proximity = 0.0015

    if direction == SignalBias.LONG:
        levels = [("VWAP", vw), ("MA15", ma15), ("support", support)]
        hits = [name for name, level in levels if low <= level * (1 + proximity) and close > level]
        return bool(hits), "bounce " + "/".join(hits) if hits else "no bounce"

    levels = [("VWAP", vw), ("MA15", ma15), ("resistance", resistance)]
    hits = [name for name, level in levels if high >= level * (1 - proximity) and close < level]
    return bool(hits), "reject " + "/".join(hits) if hits else "no reject"


def score_indicator_signal(candles: list[Candle], min_score: int = 4) -> SignalResult:
    if len(candles) < 210:
        return SignalResult(None, 0, f"need >=210 candles, got {len(candles)}")

    values = _closes(candles)
    close = values[-1]
    ema50 = ema_series(values, 50)[-1]
    ema200 = ema_series(values, 200)[-1]
    rsis = rsi_series(values, 14)
    macd_line, macd_signal = macd(values)

    long_checks: list[tuple[bool, str]] = [
        (close > ema50, "price>EMA50"),
        (ema50 > ema200, "EMA50>EMA200"),
    ]
    short_checks: list[tuple[bool, str]] = [
        (close < ema50, "price<EMA50"),
        (ema50 < ema200, "EMA50<EMA200"),
    ]

    long_bounce, long_bounce_reason = _bounce_or_reject(candles, SignalBias.LONG)
    short_reject, short_reject_reason = _bounce_or_reject(candles, SignalBias.SHORT)
    long_checks.append((long_bounce, long_bounce_reason))
    short_checks.append((short_reject, short_reject_reason))

    rsi_prev, rsi_now = rsis[-2], rsis[-1]
    long_checks.append((rsi_now > 50 and rsi_now >= rsi_prev, f"RSI up {rsi_now:.1f}"))
    short_checks.append((rsi_now < 50 and rsi_now <= rsi_prev, f"RSI down {rsi_now:.1f}"))

    macd_prev, macd_now = macd_line[-2], macd_line[-1]
    sig_prev, sig_now = macd_signal[-2], macd_signal[-1]
    long_checks.append((_crossed_above(macd_prev, macd_now, sig_prev, sig_now) or (macd_now > sig_now and macd_now > macd_prev), "MACD bullish"))
    short_checks.append((_crossed_below(macd_prev, macd_now, sig_prev, sig_now) or (macd_now < sig_now and macd_now < macd_prev), "MACD bearish"))

    long_score = sum(1 for ok, _ in long_checks if ok)
    short_score = sum(1 for ok, _ in short_checks if ok)

    if long_score >= min_score and long_score >= short_score:
        reasons = [label for ok, label in long_checks if ok]
        return SignalResult(Side.BUY, long_score, "; ".join(reasons))
    if short_score >= min_score:
        reasons = [label for ok, label in short_checks if ok]
        return SignalResult(Side.SELL, short_score, "; ".join(reasons))

    return SignalResult(None, max(long_score, short_score), f"no setup long={long_score}/5 short={short_score}/5")
