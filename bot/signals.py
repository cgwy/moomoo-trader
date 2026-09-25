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


# ============================================ breakout strategy (low frequency)
"""Confluence breakout strategy: rare, high-conviction, long-only.

Entry (ALL must hold on the last closed bar):
  1. close > highest high of the prior ``breakout_n`` bars (new 100-day high)
     AND the previous bar was not already a breakout (edge-triggered, so one
     ticket per breakout, not one per day of the run-up)
  2. close > SMA(``trend_sma``) — only trade with the long-term trend
  3. ADX(``adx_period``) > ``adx_min`` — a trend exists, not chop
  Volume ratio vs the prior ``volume_n`` bars is reported on the ticket as
  context (not a veto: it showed no consistent in-sample edge and bans
  index-ETF breakouts, which rarely spike volume).

Exit (ANY fires):
  1. close < lowest low of the prior ``breakout_n`` bars (breakdown), or
  2. close < SMA(``trend_sma``) (trend broken), or
  3. close < peak_since_entry - ``atr_mult`` x ATR(``atr_period``)
     (trailing stop)

``position`` is {"entry_date": "YYYY-MM-DD", "entry_price": float,
"peak": float}. Callers (live scanner / backtest) own persistence.
"""


def atr(bars: list[dict], period: int = 14) -> list[float | None]:
    """Wilder's ATR from high/low/close. First ``period`` entries are None."""
    n = len(bars)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period + 1:
        return out
    highs = [float(b.get("high", b["close"])) for b in bars]
    lows = [float(b.get("low", b["close"])) for b in bars]
    closes = [float(b["close"]) for b in bars]
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    s = sum(tr[1:period + 1])
    out[period] = s / period
    for i in range(period + 1, n):
        s = s - s / period + tr[i]
        out[i] = s / period
    return out


def adx(bars: list[dict], period: int = 14) -> list[float | None]:
    """Wilder's ADX from high/low/close. First ``2*period`` entries are None."""
    n = len(bars)
    out: list[float | None] = [None] * n
    if period <= 0 or n < 2 * period + 1:
        return out
    highs = [float(b.get("high", b["close"])) for b in bars]
    lows = [float(b.get("low", b["close"])) for b in bars]
    closes = [float(b["close"]) for b in bars]
    pdm = [0.0] * n
    mdm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    sp, sm, st = sum(pdm[1:period + 1]), sum(mdm[1:period + 1]), sum(tr[1:period + 1])
    dx = [0.0] * n
    for i in range(period, n):
        if i > period:
            sp = sp - sp / period + pdm[i]
            sm = sm - sm / period + mdm[i]
            st = st - st / period + tr[i]
        pdi = 100.0 * sp / st if st else 0.0
        mdi = 100.0 * sm / st if st else 0.0
        denom = pdi + mdi
        dx[i] = 100.0 * abs(pdi - mdi) / denom if denom else 0.0
    a = sum(dx[period + 1:2 * period + 1]) / period
    out[2 * period] = a
    for i in range(2 * period + 1, n):
        a = (a * (period - 1) + dx[i]) / period
        out[i] = a
    return out


def _series(bars: list[dict]):
    closes = [float(b["close"]) for b in bars]
    highs = [float(b.get("high", b["close"])) for b in bars]
    lows = [float(b.get("low", b["close"])) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    return closes, highs, lows, vols


def breakout_entry_signal(symbol: str, closed_bars: list[dict],
                          cfg: dict) -> dict | None:
    """Confluence entry ticket, or None. ``closed_bars`` oldest -> newest."""
    n = int(cfg.get("breakout_n", 100))
    sma_long = int(cfg.get("trend_sma", 200))
    vol_n = int(cfg.get("volume_n", 20))
    adx_period = int(cfg.get("adx_period", 14))
    adx_min = float(cfg.get("adx_min", 20))
    if len(closed_bars) < max(n + 2, sma_long, 2 * adx_period + 1, vol_n + 1):
        return None
    closes, highs, lows, vols = _series(closed_bars)
    bar_date = str(closed_bars[-1]["date"])[:10]
    last_close = closes[-1]

    # 1. new N-day high, edge-triggered (yesterday was not a breakout)
    prev_high = max(highs[-(n + 1):-1])
    prev_high_yday = max(highs[-(n + 2):-2])
    if not (last_close > prev_high and closes[-2] <= prev_high_yday):
        return None
    # 2. with the long-term trend
    trend = sma(closes, sma_long)
    if trend[-1] is None or not last_close > trend[-1]:
        return None
    # 3. volume note (context only, NOT a veto: in-sample ablation showed no
    #    consistent edge, and it structurally bans index ETFs like VOO whose
    #    breakouts don't spike volume). Reported on the ticket for judgment.
    vprev = vols[-(vol_n + 1):-1]
    vavg = sum(vprev) / len(vprev)
    vratio = (vols[-1] / vavg) if vavg > 0 else 1.0
    # 4. trend strength, not chop
    a = adx(closed_bars, adx_period)
    if a[-1] is None or not a[-1] > adx_min:
        return None
    return {
        "symbol": symbol,
        "type": "breakout_entry",
        "direction": "bullish",
        "bar_date": bar_date,
        "details": {
            "close": last_close,
            f"prev_{n}d_high": round(prev_high, 4),
            f"sma_{sma_long}": round(trend[-1], 4),
            "volume": vols[-1],
            "volume_ratio": round(vratio, 2),
            "volume_note": f"{vratio:.1f}x {vol_n}d avg (context only)",
            f"adx_{adx_period}": round(a[-1], 2),
        },
    }


def breakout_exit_signal(symbol: str, closed_bars: list[dict], position: dict,
                         cfg: dict) -> dict | None:
    """Exit ticket with reason, or None. ``position`` needs entry_date/peak."""
    n = int(cfg.get("breakout_n", 100))
    sma_long = int(cfg.get("trend_sma", 200))
    atr_period = int(cfg.get("atr_period", 14))
    atr_mult = float(cfg.get("atr_mult", 2.5))
    if len(closed_bars) < max(n + 1, sma_long, atr_period + 1):
        return None
    closes, highs, lows, _ = _series(closed_bars)
    bar_date = str(closed_bars[-1]["date"])[:10]
    last_close = closes[-1]
    entry_date = str(position.get("entry_date", ""))[:10]
    peak = float(position.get("peak", 0) or 0)
    for b, c in zip(closed_bars, closes):
        if str(b["date"])[:10] >= entry_date and c > peak:
            peak = c

    reasons = []
    if last_close < min(lows[-(n + 1):-1]):
        reasons.append(f"breakdown below prior {n}d low")
    trend = sma(closes, sma_long)
    if trend[-1] is not None and last_close < trend[-1]:
        reasons.append(f"close below SMA({sma_long})")
    av = atr(closed_bars, atr_period)
    stop = peak - atr_mult * av[-1] if av[-1] else None
    if stop is not None and last_close < stop:
        reasons.append(f"trailing stop {atr_mult}xATR({atr_period})")
    if not reasons:
        return None
    pnl_pct = (last_close / float(position["entry_price"]) - 1.0) * 100.0
    return {
        "symbol": symbol,
        "type": "breakout_exit",
        "direction": "bearish",
        "bar_date": bar_date,
        "details": {
            "close": last_close,
            "reasons": reasons,
            "entry_date": entry_date,
            "entry_price": float(position["entry_price"]),
            "peak": round(peak, 4),
            "pnl_pct": round(pnl_pct, 2),
        },
    }
