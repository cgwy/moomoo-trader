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


# ------------------------------------------------- breakout strategy tests

from bot.signals import (adx, atr, breakout_entry_signal,
                         breakout_exit_signal)


def make_ohlc(closes, vol=1000.0):
    """OHLC bars with a small fixed daily range around each close."""
    return [{"date": f"2020-01-{(i % 28) + 1:02d}", "close": c,
             "high": c * 1.005, "low": c * 0.995, "volume": vol}
            for i, c in enumerate(closes)]


BCFG = {"breakout_n": 20, "trend_sma": 30, "volume_n": 10,
        "adx_period": 10, "adx_min": 15.0, "atr_period": 10, "atr_mult": 2.5}


def test_atr_flat_market():
    bars = make_ohlc([100.0] * 30)
    a = atr(bars, 10)
    assert a[10] is not None
    # TR each day ~= 1% of 100 -> ATR ~= 1.0
    assert abs(a[-1] - 1.0) < 0.05


def test_adx_trend_vs_chop():
    import random
    trend = make_ohlc([100 + i for i in range(60)])          # steady climb
    rng = random.Random(42)
    closes = [100.0]
    for _ in range(59):  # random walk: no persistent direction
        closes.append(closes[-1] + rng.uniform(-1.5, 1.5))
    chop = make_ohlc(closes)
    a_trend = adx(trend, 10)[-1]
    a_chop = adx(chop, 10)[-1]
    assert a_trend is not None and a_chop is not None
    assert 0 <= a_chop <= 100 and 0 <= a_trend <= 100
    assert a_trend > 50 and a_chop < 40  # strong trend reads much higher


def test_breakout_entry_fires():
    # 40 flat days, then a jump on big volume in an uptrend
    closes = [100.0] * 40 + [100 + i * 0.5 for i in range(1, 15)] + [112.0]
    bars = make_ohlc(closes)
    bars[-1]["volume"] = 10000.0  # 10x spike
    sig = breakout_entry_signal("US.VOO", bars, BCFG)
    assert sig is not None
    assert sig["type"] == "breakout_entry" and sig["direction"] == "bullish"
    assert sig["details"]["volume_ratio"] > 1.5


def test_breakout_entry_edge_triggered_once():
    # ramp into the breakout so ADX is elevated; volume spikes on both bars
    closes = [100.0] * 40 + [100 + i * 0.5 for i in range(1, 15)] + [112.0, 113.0]
    bars = make_ohlc(closes)
    bars[-2]["volume"] = 10000.0
    bars[-1]["volume"] = 10000.0
    first = breakout_entry_signal("US.VOO", bars[:-1], BCFG)
    second = breakout_entry_signal("US.VOO", bars, BCFG)
    assert first is not None and second is None  # no repeat ticket


def test_breakout_entry_vetoed_below_trend():
    # breakout after a long decline: still below SMA(30)
    closes = [200 - i * 2 for i in range(40)] + [115.0]
    bars = make_ohlc(closes)
    bars[-1]["volume"] = 10000.0
    assert breakout_entry_signal("US.VOO", bars, BCFG) is None


def test_breakout_entry_reports_volume_context():
    # volume is context on the ticket now, not a veto: flat volume still fires
    closes = [100.0] * 40 + [100 + i * 0.5 for i in range(1, 15)] + [112.0]
    bars = make_ohlc(closes)  # volume flat at 1000 -> ratio 1.0
    sig = breakout_entry_signal("US.VOO", bars, BCFG)
    assert sig is not None
    assert sig["details"]["volume_ratio"] == 1.0
    assert "context only" in sig["details"]["volume_note"]


def test_breakout_exit_trailing_stop():
    closes = [100 + i * 0.5 for i in range(50)]  # uptrend
    bars = make_ohlc(closes)
    pos = {"entry_date": "2020-01-01", "entry_price": 100.0, "peak": 124.0}
    # now crash 10%: trailing stop = 124 - 2.5*ATR(~1.2) >> current
    crash = make_ohlc([110.0, 105.0, 100.0])
    all_bars = bars + crash
    sig = breakout_exit_signal("US.VOO", all_bars, pos, BCFG)
    assert sig is not None
    assert sig["type"] == "breakout_exit"
    assert any("trailing stop" in r for r in sig["details"]["reasons"])
    assert sig["details"]["pnl_pct"] == 0.0  # exited flat vs 100 entry


def test_breakout_exit_below_trend():
    closes = [150.0] * 40 + [140.0]  # sudden drop below SMA(30)~149
    bars = make_ohlc(closes)
    pos = {"entry_date": "2020-01-01", "entry_price": 120.0, "peak": 150.0}
    sig = breakout_exit_signal("US.VOO", bars, pos, BCFG)
    assert sig is not None
    assert any("SMA" in r for r in sig["details"]["reasons"])


def test_breakout_no_exit_while_healthy():
    closes = [100 + i * 0.5 for i in range(50)] + [124.5, 125.0]
    bars = make_ohlc(closes)
    pos = {"entry_date": "2020-01-01", "entry_price": 100.0, "peak": 120.0}
    assert breakout_exit_signal("US.VOO", bars, pos, BCFG) is None
