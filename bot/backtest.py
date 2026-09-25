"""Backtest the breakout strategy on Yahoo daily bars.

    python -m bot.backtest [--years 10] [--config config.yaml]

Long-only, one position per symbol, no leverage, no transaction costs (stated
in the output — at this frequency costs are negligible vs. signal noise).
Entry/exit logic is the SAME pure functions the live scanner uses
(signals.breakout_entry_signal / breakout_exit_signal), so the backtest
measures what would actually run.

Cooldown: no new entry within ``cooldown_days`` after an exit (default 60).
"""

from __future__ import annotations

import argparse
from datetime import date

from .config import load_config
from .signals import breakout_entry_signal, breakout_exit_signal
from .yahoo import YahooClient


def _as_date(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def backtest_symbol(symbol: str, bars: list[dict], cfg: dict) -> dict:
    cool = int(cfg.get("cooldown_days", 60))
    warmup = max(int(cfg.get("breakout_n", 100)) + 2,
                 int(cfg.get("trend_sma", 200)),
                 2 * int(cfg.get("adx_period", 14)) + 1,
                 int(cfg.get("volume_n", 20)) + 1)
    trades: list[dict] = []
    position: dict | None = None
    last_exit: date | None = None
    equity = 1.0
    peak_eq = 1.0
    max_dd = 0.0
    # Indicators only look back <= max(breakout_n+2, trend_sma, 2*adx+1) bars,
    # so a trailing 500-bar window is exactly equivalent and much faster.
    # Peak is maintained incrementally in `position`, so the window never
    # needs to reach back to the entry bar.
    WIN = 500

    for i in range(warmup, len(bars)):
        closed = bars[max(0, i - WIN + 1):i + 1]
        today = _as_date(bars[i]["date"])
        cur_close = float(bars[i]["close"])
        if position is None:
            if last_exit is not None and (today - last_exit).days < cool:
                continue
            sig = breakout_entry_signal(symbol, closed, cfg)
            if sig:
                position = {
                    "entry_date": str(bars[i]["date"])[:10],
                    "entry_price": cur_close,
                    "peak": cur_close,
                }
        else:
            position["peak"] = max(position["peak"], cur_close)
            # mark-to-market for drawdown before checking exit
            prev_close = float(bars[i - 1]["close"])
            if prev_close > 0:
                equity *= cur_close / prev_close
            peak_eq = max(peak_eq, equity)
            max_dd = min(max_dd, equity / peak_eq - 1.0)
            sig = breakout_exit_signal(symbol, closed, position, cfg)
            if sig:
                ret = cur_close / position["entry_price"] - 1.0
                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": str(bars[i]["date"])[:10],
                    "entry_px": position["entry_price"],
                    "exit_px": cur_close,
                    "ret": ret,
                    "reasons": sig["details"]["reasons"],
                })
                position = None
                last_exit = today
    # close any open position at the last bar for accounting
    if position is not None:
        cur_close = float(bars[-1]["close"])
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date": str(bars[-1]["date"])[:10] + " (open)",
            "entry_px": position["entry_price"],
            "exit_px": cur_close,
            "ret": cur_close / position["entry_price"] - 1.0,
            "reasons": ["still open"],
        })
    years = (_as_date(bars[-1]["date"]) - _as_date(bars[warmup]["date"])).days / 365.25
    wins = [t for t in trades if t["ret"] > 0]
    total_ret = 1.0
    for t in trades:
        total_ret *= 1.0 + t["ret"]
    total_ret -= 1.0
    bh = float(bars[-1]["close"]) / float(bars[warmup]["close"]) - 1.0
    return {
        "symbol": symbol,
        "years": years,
        "n_trades": len(trades),
        "trades_per_year": len(trades) / years if years else 0,
        "win_rate": len(wins) / len(trades) if trades else 0,
        "avg_ret": sum(t["ret"] for t in trades) / len(trades) if trades else 0,
        "total_ret": total_ret,
        "max_dd": max_dd,
        "buy_hold": bh,
        "trades": trades,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the breakout strategy.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--years", type=int, default=10)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    bcfg = cfg["strategy"].get("breakout", {})
    client = YahooClient()
    results = []
    for symbol in cfg["symbols"]:
        print(f"fetching {symbol} ...")
        bars = client.get_daily_klines(symbol, args.years * 365)
        r = backtest_symbol(symbol, bars, bcfg)
        results.append(r)
        print(f"  {r['n_trades']} trades over {r['years']:.1f}y "
              f"({r['trades_per_year']:.2f}/y), win {r['win_rate']:.0%}, "
              f"avg {r['avg_ret']:+.1%}, total {r['total_ret']:+.0%}, "
              f"maxDD {r['max_dd']:.0%}, buy&hold {r['buy_hold']:+.0%}")
    print("\n=== per-trade detail ===")
    for r in results:
        for t in r["trades"]:
            print(f"{r['symbol']} {t['entry_date']} -> {t['exit_date']}: "
                  f"{t['ret']:+.1%}  ({'; '.join(t['reasons'])})")
    print("\n(no costs modeled; at ~1-3 round trips/year they are negligible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
