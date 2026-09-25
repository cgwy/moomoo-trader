"""Conviction layer: insider (Form 4) veto + short-interest context.

Fail-open by design: if SEC EDGAR or Nasdaq are unreachable, the price
signal still fires and the ticket notes the missing data. A data outage
must never silently suppress signals.

Results are cached on disk (.cache/, gitignored): insider summaries change
slowly (Form 4s trickle in daily), short interest only twice a month.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
INSIDER_TTL_S = 24 * 3600
SHORT_TTL_S = 7 * 24 * 3600


def _load(name: str, max_age_s: float) -> dict | None:
    try:
        p = CACHE_DIR / name
        if p.exists() and time.time() - p.stat().st_mtime < max_age_s:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001 - cache is best-effort
        pass
    return None


def _save(name: str, payload: dict) -> None:
    try:
        p = CACHE_DIR / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))
    except Exception:  # noqa: BLE001 - cache is best-effort
        pass


def _plain_ticker(symbol: str) -> str:
    return symbol.split(".")[-1].upper()


def check_conviction(symbol: str, cfg: dict) -> dict:
    """Veto / annotate a breakout entry signal.

    Returns {"vetoed", "veto_reason", "details", "notes"}.
    ``vetoed`` is True only when insider data was actually retrieved and
    shows material net selling. Every fetch failure degrades to fail-open
    (stale cache if any, else a note on the ticket).
    """
    icfg = cfg.get("insider", {}) if isinstance(cfg, dict) else {}
    window = int(icfg.get("window_days", 90))
    veto_on = bool(icfg.get("veto_on_net_selling", True))
    min_sell = float(icfg.get("min_net_sell_usd", 1_000_000))
    t = _plain_ticker(symbol)

    vetoed = False
    veto_reason: str | None = None
    details: dict = {}
    notes: list[str] = []

    # --- insider transactions (Form 4): the veto ---
    cname = f"insider/{t}_{window}d.json"
    ins = _load(cname, INSIDER_TTL_S)
    if ins is None:
        try:
            from .insider import get_insider_summary
            ins = get_insider_summary(t, window_days=window)
            _save(cname, ins)
        except Exception as e:  # noqa: BLE001 - fail open, never suppress
            ins = _load(cname, float("inf"))  # stale cache beats no data
            notes.append(f"insider data unavailable ({e})"
                         + ("; using stale cache" if ins else "")
                         + " — signal not vetoed")
    if ins is not None:
        net = float(ins.get("net_value", 0.0))
        details["insider"] = {
            "window_days": window,
            "net_usd": net,
            "buy_usd": ins.get("buy_value"),
            "sell_usd": ins.get("sell_value"),
            "n_buys": ins.get("n_buys"),
            "n_sells": ins.get("n_sells"),
            "asof": ins.get("asof"),
        }
        if veto_on and net < -min_sell:
            vetoed = True
            veto_reason = (
                f"insider veto: net selling ${-net:,.0f} over {window}d "
                f"({ins.get('n_sells')} sells vs {ins.get('n_buys')} buys)")

    # --- short interest: context only, never a veto ---
    sname = f"shortinterest/{t}.json"
    si = _load(sname, SHORT_TTL_S)
    if si is None:
        try:
            from .shortinterest import get_short_interest
            si = get_short_interest(t)
            _save(sname, si)
        except Exception as e:  # noqa: BLE001 - context only, fail open
            si = _load(sname, float("inf"))
            notes.append(f"short-interest unavailable ({e})"
                         + ("; using stale cache" if si else ""))
    if si is not None:
        details["short_interest"] = {
            "shares_short": si.get("short_interest"),
            "days_to_cover": si.get("days_to_cover"),
            "settlement_date": si.get("settlement_date"),
            "source": si.get("source"),
        }

    return {"vetoed": vetoed, "veto_reason": veto_reason,
            "details": details, "notes": notes}
