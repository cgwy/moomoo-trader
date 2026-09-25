"""Semi-auto trading assistant: scan watchlist -> signal ticket -> YOU confirm -> order.

Usage:
    python -m bot.main [--config config.yaml] [--once] [--dry-run]

* --once     : single scan pass, then exit (good for cron).
* --dry-run  : no OpenD needed. Runs signal logic on synthetic data and
               prints a sample ticket. Exercises the whole pipeline except
               the live connection and order placement.
* (no flags): loop forever, sleeping scan.poll_interval_minutes between scans.

Every order requires typing 'confirm'. Default trade_env=SIMULATE (paper).
REAL money additionally requires typing 'TRADE REAL' at startup.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta

from .config import load_config
from .data import QuoteClient
from .executor import Executor, OrderRefused
from .notify import emit, format_ticket, suggested_side
from .signals import detect_signals, get_closed_bars


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
    print("=== DRY RUN: synthetic data, no OpenD, no orders ===\n")
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
            print(format_ticket(sig, qty=1, limit_price=sig["details"]["close"]))
            print(f"[dry-run] would prompt: Type 'confirm' to place "
                  f"{suggested_side(sig)} 1 x {symbol} — skipped in dry-run.\n")
    print("=== DRY RUN OK ===")
    return 0


# -------------------------------------------------------------------- live

def scan_once(cfg: dict, quotes: QuoteClient, executor: Executor,
              prompt_fn=input) -> int:
    """One pass over the watchlist. Returns number of signals found."""
    n_signals = 0
    strategy = cfg["strategy"]
    qty = int(cfg["trade"].get("default_qty", 1))
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
            price = float(sig["details"]["close"])
            emit(sig, log_file=log_file, qty=qty, limit_price=price)
            side = suggested_side(sig)
            answer = prompt_fn(
                f"Type 'confirm' to place {side} {qty} x {symbol} "
                f"limit @ {price:.2f} [{cfg['trade']['trade_env']}], Enter to skip: "
            ).strip()
            if answer != "confirm":
                print("skipped.\n")
                continue
            try:
                result = executor.place_limit_order(symbol, side, qty, price)
                print(f"order placed: {result}\n")
            except OrderRefused as e:
                print(f"ORDER REFUSED: {e}\n")
            except Exception as e:  # noqa: BLE001
                print(f"order failed: {e}\n")
    return n_signals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Semi-auto trading assistant (moomoo OpenAPI).")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--once", action="store_true", help="single scan pass, then exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="synthetic data, no OpenD, no orders")
    args = ap.parse_args(argv)

    if args.dry_run:
        return dry_run()

    cfg = load_config(args.config)
    opend = cfg["opend"]
    trade_env = cfg["trade"]["trade_env"]

    allow_real = False
    if trade_env == "REAL":
        print("⚠️  config requests REAL-MONEY trading.")
        if input("Type 'TRADE REAL' to arm real orders, anything else aborts: ").strip() != "TRADE REAL":
            print("aborted.")
            return 1
        allow_real = True

    print(f"Connecting to OpenD at {opend['host']}:{opend['port']} ...")
    quotes = QuoteClient(opend["host"], opend["port"])
    executor = Executor(opend["host"], opend["port"], trade_env,
                        password=cfg["trade"].get("password"), allow_real=allow_real)
    try:
        while True:
            n = scan_once(cfg, quotes, executor)
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
        executor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
