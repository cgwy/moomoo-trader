"""Pure signal logic: MA cross + RSI zone entries on daily bars.

No network, no OpenD, no I/O — fully unit-testable.

Conventions
-----------
* ``bars`` are oldest -> newest dicts: {"date": "YYYY-MM-DD", "close": float}.
* Signals fire on the last **CLOSED** bar only (no repainting). Callers must
  pass already-closed bars; see :func:`get_closed_bars`.
* A signal is a dict: {"symbol", "type", "direction", "bar_date", "details"}.
  ``type`` is one of "ma_golden_cross" | "ma_death_cross" | "rsi_oversold" |
  "rsi_overbought"; ``direction`` is "bullish" | "bearish".
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")
US_MARKET_CLOSE = dtime(16, 0)  # 4pm ET; after this a same-day daily bar is closed


# ---------------------------------------------------------------- indicators

def sma(values: list[float], n: int) -> list[float | None]:
    """Simple moving average; entries with insufficient history are None."""
    out: list[float | None] = [None] * len(values)
    if n <= 0:
        return out
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= n:
            window_sum -= values[i - n]
        if i >= n - 1:
            out[i] = window_sum / n
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI. First ``period`` entries are None (warmup).

    Flat/no-loss stretches return 100.0 when there were gains, 50.0 when the
    market was perfectly flat (avoids division by zero).
    """
    out: list[float | None] = [None] * len(closes)
    if period <= 0 or len(closes) < period + 1:
        return out
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


# ------------------------------------------------------- closed-bar handling

def _as_date(bar_date) -> "datetime.date":
    from datetime import date as date_cls

    if isinstance(bar_date, date_cls):
        return bar_date
    return datetime.strptime(str(bar_date)[:10], "%Y-%m-%d").date()


def get_closed_bars(bars: list[dict], now: datetime | None = None) -> list[dict]:
    """Drop the in-progress daily bar.

    A bar dated today (US Eastern) is still forming unless ``now`` is past the
    4pm ET close. Future-dated bars are dropped defensively.
    """
    if now is None:
        now = datetime.now(US_EASTERN)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=US_EASTERN)
    today_et = now.astimezone(US_EASTERN).date()
    market_closed = now.astimezone(US_EASTERN).timetz() >= US_MARKET_CLOSE
    closed = []
    for b in bars:
        d = _as_date(b["date"])
        if d > today_et:
            continue
        if d == today_et and not market_closed:
            continue
        closed.append(b)
    return closed


# ------------------------------------------------------------- signal detect

def _crossed_up(prev_a, prev_b, cur_a, cur_b) -> bool:
    return prev_a is not None and prev_b is not None and prev_a <= prev_b and cur_a > cur_b


def _crossed_down(prev_a, prev_b, cur_a, cur_b) -> bool:
    return prev_a is not None and prev_b is not None and prev_a >= prev_b and cur_a < cur_b


def detect_signals(symbol: str, closed_bars: list[dict], cfg: dict) -> list[dict]:
    """Detect MA-cross and RSI signals on the last closed bar.

    ``cfg`` keys: ma_fast, ma_slow, rsi_period, rsi_overbought, rsi_oversold,
    use_ma_cross, use_rsi. Returns a list (0-2 signals).
    """
    signals: list[dict] = []
    if len(closed_bars) < 2:
        return signals
    closes = [float(b["close"]) for b in closed_bars]
    bar_date = str(closed_bars[-1]["date"])[:10]
    last_close = closes[-1]

    if cfg.get("use_ma_cross", True):
        ma_fast = int(cfg.get("ma_fast", 5))
        ma_slow = int(cfg.get("ma_slow", 20))
        fast = sma(closes, ma_fast)
        slow = sma(closes, ma_slow)
        # Need two fully-formed MA points to judge a cross on the last bar.
        if len(closes) >= ma_slow + 1 and fast[-2] is not None and slow[-2] is not None:
            if _crossed_up(fast[-2], slow[-2], fast[-1], slow[-1]):
                signals.append({
                    "symbol": symbol,
                    "type": "ma_golden_cross",
                    "direction": "bullish",
                    "bar_date": bar_date,
                    "details": {
                        "close": last_close,
                        "ma_fast": round(fast[-1], 4),
                        "ma_slow": round(slow[-1], 4),
                        "ma_fast_prev": round(fast[-2], 4),
                        "ma_slow_prev": round(slow[-2], 4),
                    },
                })
            elif _crossed_down(fast[-2], slow[-2], fast[-1], slow[-1]):
                signals.append({
                    "symbol": symbol,
                    "type": "ma_death_cross",
                    "direction": "bearish",
                    "bar_date": bar_date,
                    "details": {
                        "close": last_close,
                        "ma_fast": round(fast[-1], 4),
                        "ma_slow": round(slow[-1], 4),
                        "ma_fast_prev": round(fast[-2], 4),
                        "ma_slow_prev": round(slow[-2], 4),
                    },
                })

    if cfg.get("use_rsi", True):
        period = int(cfg.get("rsi_period", 14))
        overbought = float(cfg.get("rsi_overbought", 70))
        oversold = float(cfg.get("rsi_oversold", 30))
        r = rsi(closes, period)
        if r[-2] is not None and r[-1] is not None:
            # Bullish: RSI crosses DOWN through the oversold line into the zone.
            if r[-2] >= oversold > r[-1]:
                signals.append({
                    "symbol": symbol,
                    "type": "rsi_oversold",
                    "direction": "bullish",
                    "bar_date": bar_date,
                    "details": {
                        "close": last_close,
                        "rsi": round(r[-1], 2),
                        "rsi_prev": round(r[-2], 2),
                        "rsi_period": period,
                        "oversold": oversold,
                    },
                })
            # Bearish: RSI crosses UP through the overbought line into the zone.
            elif r[-2] <= overbought < r[-1]:
                signals.append({
                    "symbol": symbol,
                    "type": "rsi_overbought",
                    "direction": "bearish",
                    "bar_date": bar_date,
                    "details": {
                        "close": last_close,
                        "rsi": round(r[-1], 2),
                        "rsi_prev": round(r[-2], 2),
                        "rsi_period": period,
                        "overbought": overbought,
                    },
                })

    return signals
