"""Unit tests for bot.signals — synthetic data only, no OpenD."""

from datetime import date, datetime, timedelta

import pytest

from bot.signals import US_EASTERN, detect_signals, get_closed_bars, rsi, sma

MA_CFG = {
    "use_ma_cross": True, "ma_fast": 3, "ma_slow": 5,
    "use_rsi": False,
}
RSI_CFG = {
    "use_ma_cross": False,
    "use_rsi": True, "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
}


def make_bars(closes, start="2026-01-05"):
    d0 = date.fromisoformat(start)
    return [{"date": (d0 + timedelta(days=i)).isoformat(), "close": float(c)}
            for i, c in enumerate(closes)]


# ------------------------------------------------------------ MA cross tests

def test_golden_cross_detected():
    # fast(3) crosses above slow(5) exactly on the last bar:
    # fast[-2]=12.33<=slow[-2]=14.2 ; fast[-1]=15.67>slow[-1]=15.4
    sigs = detect_signals("US.VOO", make_bars([20, 18, 16, 14, 12, 11, 24]), MA_CFG)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["type"] == "ma_golden_cross"
    assert s["direction"] == "bullish"
    assert s["symbol"] == "US.VOO"
    assert s["bar_date"] == "2026-01-11"
    assert set(s) == {"symbol", "type", "direction", "bar_date", "details"}


def test_death_cross_detected():
    # fast[-2]=17.67>=slow[-2]=15.8 ; fast[-1]=14.33<slow[-1]=14.6
    sigs = detect_signals("US.VOO", make_bars([10, 12, 14, 16, 18, 19, 6]), MA_CFG)
    assert len(sigs) == 1
    assert sigs[0]["type"] == "ma_death_cross"
    assert sigs[0]["direction"] == "bearish"


def test_no_cross_no_signal():
    # steady uptrend: fast stays above slow, never crosses on last bar
    assert detect_signals("US.VOO", make_bars([10, 11, 12, 13, 14, 15, 16]), MA_CFG) == []
    # flat market
    assert detect_signals("US.VOO", make_bars([10] * 10), MA_CFG) == []
    # steady downtrend: fast stays below slow
    assert detect_signals("US.VOO", make_bars([16, 15, 14, 13, 12, 11, 10]), MA_CFG) == []


def test_insufficient_data_no_crash():
    cfg = dict(MA_CFG, ma_fast=5, ma_slow=20)
    assert detect_signals("US.VOO", make_bars([100, 101, 102]), cfg) == []
    assert detect_signals("US.VOO", [], cfg) == []
    assert detect_signals("US.VOO", make_bars([100]), cfg) == []


def test_no_repaint_on_unclosed_bar():
    # 6 closed bars (no cross) + today's still-forming bar that WOULD fake a cross.
    bars = make_bars([20, 18, 16, 14, 12, 11, 24], start="2026-09-18")
    # bars[-1] is dated 2026-09-24 == "today" in this scenario
    now_morning = datetime(2026, 9, 24, 10, 0, tzinfo=US_EASTERN)
    closed = get_closed_bars(bars, now=now_morning)
    assert [b["close"] for b in closed] == [20, 18, 16, 14, 12, 11]
    assert detect_signals("US.VOO", closed, MA_CFG) == []

    # control: if that bar were genuinely closed, the cross IS detected
    # (proves the test above isn't vacuous)
    assert detect_signals("US.VOO", bars, MA_CFG)[0]["type"] == "ma_golden_cross"

    # after the 4pm ET close, today's bar counts as closed
    now_evening = datetime(2026, 9, 24, 17, 30, tzinfo=US_EASTERN)
    closed2 = get_closed_bars(bars, now=now_evening)
    assert len(closed2) == 7
    assert detect_signals("US.VOO", closed2, MA_CFG)[0]["type"] == "ma_golden_cross"


# ---------------------------------------------------------------- RSI tests

def test_rsi_sanity():
    up = [100 + i for i in range(30)]
    down = [200 - i for i in range(30)]
    flat = [50.0] * 30
    assert rsi(up)[-1] > 70
    assert rsi(down)[-1] < 30
    assert rsi(flat)[-1] == 50.0
    assert rsi([1, 2, 3], period=14) == [None, None, None]  # warmup


def _find_cross(closes, period, line, direction):
    """Find first index i where RSI crosses `line` in `direction`
    ('down' = from >=line to <line, 'up' = from <=line to >line)."""
    r = rsi(closes, period)
    for i in range(1, len(r)):
        if r[i - 1] is None or r[i] is None:
            continue
        if direction == "down" and r[i - 1] >= line > r[i]:
            return i
        if direction == "up" and r[i - 1] <= line < r[i]:
            return i
    return None


def test_rsi_oversold_entry_is_bullish():
    # flat start (RSI=50) then steady bleed: RSI must cross DOWN through 30
    closes = [200.0] * 15 + [200 - 3 * i for i in range(1, 21)]
    i = _find_cross(closes, 14, 30, "down")
    assert i is not None, "synthetic data must cross into oversold"
    bars = make_bars(closes[:i + 1])
    sigs = detect_signals("US.SOXX", bars, RSI_CFG)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["type"] == "rsi_oversold"
    assert s["direction"] == "bullish"
    assert s["bar_date"] == bars[i]["date"]
    assert s["details"]["rsi"] < 30 <= s["details"]["rsi_prev"]


def test_rsi_overbought_entry_is_bearish():
    closes = [100.0] * 15 + [100 + 3 * i for i in range(1, 21)]
    i = _find_cross(closes, 14, 70, "up")
    assert i is not None, "synthetic data must cross into overbought"
    bars = make_bars(closes[:i + 1])
    sigs = detect_signals("US.AMZN", bars, RSI_CFG)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["type"] == "rsi_overbought"
    assert s["direction"] == "bearish"
    assert s["details"]["rsi"] > 70 >= s["details"]["rsi_prev"]


def test_rsi_no_signal_while_sitting_in_zone():
    # After the entry cross, RSI stays deep in the zone: no fresh signals.
    closes = [200.0] * 15 + [200 - 3 * i for i in range(1, 21)]
    i = _find_cross(closes, 14, 30, "down")
    assert i is not None
    later_bars = make_bars(closes[:i + 4])  # 3 more bars, RSI still < 30
    r = rsi([b["close"] for b in later_bars], 14)
    assert all(v is not None and v < 30 for v in r[-3:])
    assert detect_signals("US.SOXX", later_bars, RSI_CFG) == []

    # mirror: sits in overbought zone
    closes_up = [100.0] * 15 + [100 + 3 * i for i in range(1, 21)]
    j = _find_cross(closes_up, 14, 70, "up")
    assert j is not None
    later_up = make_bars(closes_up[:j + 4])
    r2 = rsi([b["close"] for b in later_up], 14)
    assert all(v is not None and v > 70 for v in r2[-3:])
    assert detect_signals("US.AMZN", later_up, RSI_CFG) == []


def test_rsi_mid_zone_no_signal():
    # choppy sideways market: RSI wiggles inside (30, 70), never crosses a line
    closes = [100 + (i % 2) * 2 - 1 for i in range(40)]  # 99,101,99,101,...
    sigs = detect_signals("US.MSFT", make_bars(closes), RSI_CFG)
    assert sigs == []


def test_ma_and_rsi_can_fire_together():
    cfg = dict(MA_CFG)
    cfg.update({"use_rsi": True, "rsi_period": 14,
                "rsi_overbought": 70, "rsi_oversold": 30})
    sigs = detect_signals("US.VOO", make_bars([20, 18, 16, 14, 12, 11, 24]), cfg)
    types = {s["type"] for s in sigs}
    assert "ma_golden_cross" in types  # RSI may or may not also fire; MA must
