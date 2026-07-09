from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from src.models import Session, Trend

ET = ZoneInfo("America/New_York")

# Silver is ~1.8x more volatile than gold on average
VOLATILITY_MULTIPLIER = {
    "XAU-USD.P": 1.0,
    "XAG-USD.P": 1.6,
}


def detect_session(now: datetime | None = None) -> Session:
    """
    Ondo uses internal pricing Fri 4pm ET → Sun ~6pm ET when COMEX/external feeds close.
    Grid is riskier in this window: thinner liquidity, ±5% discovery bounds at 20x.
    """
    now = now or datetime.now(tz=ET)
    wd, hour = now.weekday(), now.hour

    if wd == 4 and hour >= 16:
        return Session.WEEKEND
    if wd == 5:
        return Session.WEEKEND
    if wd == 6 and hour < 18:
        return Session.WEEKEND
    return Session.REGULAR


def detect_trend(closes: list[float], threshold_pct: float = 0.12) -> Trend:
    """EMA(6) vs EMA(18) on hourly closes — classic short-term trend filter."""
    if len(closes) < 18:
        return Trend.NEUTRAL

    def ema(values: list[float], period: int) -> float:
        k = 2 / (period + 1)
        result = values[0]
        for v in values[1:]:
            result = v * k + result * (1 - k)
        return result

    fast = ema(closes, 6)
    slow = ema(closes, 18)
    if slow == 0:
        return Trend.NEUTRAL

    diff_pct = (fast - slow) / slow * 100
    if diff_pct > threshold_pct:
        return Trend.UP
    if diff_pct < -threshold_pct:
        return Trend.DOWN
    return Trend.NEUTRAL


def level_split(levels_per_side: int, trend: Trend) -> tuple[int, int]:
    """
    Asymmetric grid in trends (research: don't stack orders against momentum).

    Uptrend   → fewer buys below (1/3), more sells above (full)
    Downtrend → more buys below (full), fewer sells above (1/3)
    Neutral   → symmetric
    """
    if trend == Trend.UP:
        buys = max(1, levels_per_side // 3)
        sells = levels_per_side
    elif trend == Trend.DOWN:
        buys = levels_per_side
        sells = max(1, levels_per_side // 3)
    else:
        buys = sells = levels_per_side
    return buys, sells


def session_spacing_multiplier(session: Session) -> float:
    return 1.5 if session == Session.WEEKEND else 1.0


def session_levels_adjustment(session: Session, levels: int) -> int:
    return max(1, levels - 1) if session == Session.WEEKEND else levels