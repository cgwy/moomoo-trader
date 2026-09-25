"""Signal scanner: watchlist -> MA/RSI signal tickets. Read-only, never trades.

This program only READS market data and prints/logs signal tickets. It has no
order-placement code at all — discovering opportunities is all it does.
What you do with a ticket (e.g. placing an order by hand in the moomoo app)
is entirely up to you, outside this program.

Usage:
    python -m bot.main [--config config.yaml] [--once] [--dry-run]

* --once     : single scan pass, then exit (good for cron).
* --dry-run  : no OpenD needed. Runs signal logic on synthetic data and
               prints sample tickets. Exercises the pipeline except the
               live connection.
* (no flags): loop forever, sleeping scan.poll_interval_minutes between scans.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta

from .config import load_config
from .data import QuoteClient
from .notify import emit, format_ticket
from .signals import (breakout_entry_signal, breakout_exit_signal,
                      detect_signals, get_closed_bars)
from .state import load as load_state, save as save_state
from .yahoo import YahooClient


# ------------------------------------------------------------------ dry run

def _synthetic_bars_ma() -> list[dict]:
    """25 flat bars, a dip, then a jump: MA(5) crosses above MA(20) on the
    last bar. Deterministic by construction (see tests)."""
    start = date(2026, 8, 1)
    closes = [100.0] * 25 + [90.0, 85.0, 80.0, 75.0, 200.0]
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": c}
            for i, c in enumerate(closes)]


def _synthetic_bars_rsi() -> list[dict]:
    """Flat start (RSI=50) then a steady bleed, truncated exactly at the bar
    where RSI crosses down through 30 -> bullish rsi_oversold ticket."""
    from .signals import rsi as rsi_fn

    start = date(2026, 7, 1)
    closes = [300.0] * 20 + [300 - 3 * i for i in range(1, 25)]
    r = rsi_fn(closes, 14)
    idx = max(i for i in range(1, len(r))
              if r[i - 1] is not None and r[i] is not None and r[i - 1] >= 30 > r[i])
    closes = closes[:idx + 1]
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": c}
            for i, c in enumerate(closes)]


def dry_run() -> int:
    print("=== DRY RUN: synthetic data, no OpenD ===\n")
    cfg = {
        "use_ma_cross": True, "ma_fast": 5, "ma_slow": 20,
        "use_rsi": True, "rsi_period": 14,
        "rsi_overbought": 70, "rsi_oversold": 30,
    }
    symbols = {"US.VOO": _synthetic_bars_ma(), "US.SOXX": _synthetic_bars_rsi()}

    for symbol, bars in symbols.items():
        closed = get_closed_bars(bars)  # all historical -> all closed
        sigs = detect_signals(symbol, closed, cfg)
        if not sigs:
            print(f"(no signal for {symbol} on synthetic data)\n")
            continue
        for sig in sigs:
            print(format_ticket(sig) + "\n")
    print("=== DRY RUN OK ===")
    return 0


# -------------------------------------------------------------------- live

def make_client(cfg):
    """Pick the market-data source. Yahoo needs nothing; OpenD needs a
    logged-in OpenD on host:port (your own machine, your own login)."""
    if cfg["data_source"] == "yahoo":
        print("data source: Yahoo Finance (no login needed)")
        return YahooClient()
    opend = cfg["opend"]
    print(f"data source: OpenD at {opend['host']}:{opend['port']} ...")
    return QuoteClient(opend["host"], opend["port"])


def scan_once(cfg: dict, quotes) -> int:
    """One pass over the watchlist. Returns number of signals found."""
    if cfg["strategy"].get("preset", "breakout") == "breakout":
        return scan_breakout(cfg, quotes)
    return scan_classic(cfg, quotes)


def scan_breakout(cfg: dict, quotes) -> int:
    """Confluence breakout scan with persistent positions (see bot/state.py)."""
    from datetime import date as date_cls

    bcfg = cfg["strategy"]["breakout"]
    log_file = cfg["notify"].get("log_file", "signals.log")
    state_file = bcfg.get("state_file", "positions.json")
    state = load_state(state_file)
    positions = state["positions"]
    last_exit = state["last_exit"]
    cooldown = int(bcfg.get("cooldown_days", 60))
    need = max(int(bcfg.get("breakout_n", 100)) + 2,
               int(bcfg.get("trend_sma", 200)),
               2 * int(bcfg.get("adx_period", 14)) + 1)
    history_days = max(cfg["scan"].get("history_days", 400), need)
    n_signals = 0

    for symbol in cfg["symbols"]:
        try:
            bars = quotes.get_daily_klines(symbol, history_days)
        except Exception as e:  # noqa: BLE001 - keep scanning other symbols
            print(f"[{symbol}] data error: {e}", file=sys.stderr)
            continue
        closed = get_closed_bars(bars)
        if not closed:
            continue
        today = str(closed[-1]["date"])[:10]
        pos = positions.get(symbol)
        if pos is not None:
            sig = breakout_exit_signal(symbol, closed, pos, bcfg)
            if sig:
                n_signals += 1
                emit(sig, log_file=log_file)
                del positions[symbol]
                last_exit[symbol] = today
        else:
            le = last_exit.get(symbol)
            if le and (date_cls.fromisoformat(today)
                       - date_cls.fromisoformat(le)).days < cooldown:
                continue
            sig = breakout_entry_signal(symbol, closed, bcfg)
            if sig:
                n_signals += 1
                emit(sig, log_file=log_file)
                px = float(closed[-1]["close"])
                positions[symbol] = {"entry_date": today,
                                     "entry_price": px, "peak": px}
    save_state(state_file, state)
    return n_signals


def scan_classic(cfg: dict, quotes) -> int:
    """Original MA-cross + RSI scan (stateless)."""
    n_signals = 0
    strategy = cfg["strategy"]
    log_file = cfg["notify"].get("log_file", "signals.log")

    for symbol in cfg["symbols"]:
        try:
            bars = quotes.get_daily_klines(symbol, cfg["scan"].get("history_days", 120))
        except Exception as e:  # noqa: BLE001 - keep scanning other symbols
            print(f"[{symbol}] data error: {e}", file=sys.stderr)
            continue
        closed = get_closed_bars(bars)
        for sig in detect_signals(symbol, closed, strategy):
            n_signals += 1
            emit(sig, log_file=log_file)
    return n_signals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Signal scanner. Read-only: prints signal tickets, never trades.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--once", action="store_true", help="single scan pass, then exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="synthetic data, no OpenD connection")
    args = ap.parse_args(argv)

    if args.dry_run:
        return dry_run()

    cfg = load_config(args.config)
    quotes = make_client(cfg)
    try:
        while True:
            n = scan_once(cfg, quotes)
            print(f"scan done: {n} signal(s).")
            if args.once:
                break
            mins = int(cfg["scan"].get("poll_interval_minutes", 60))
            print(f"sleeping {mins} min ... (Ctrl-C to stop)")
            time.sleep(mins * 60)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        quotes.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
