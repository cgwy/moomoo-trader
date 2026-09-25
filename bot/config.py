"""Config loading. Trade password comes ONLY from the MOOMOO_TRADE_PWD env var."""

from __future__ import annotations

import os
import yaml

DEFAULTS = {
    "opend": {"host": "127.0.0.1", "port": 11111},
    "trade": {"trade_env": "SIMULATE", "default_qty": 1},
    "symbols": [],
    "strategy": {
        "use_ma_cross": True,
        "ma_fast": 5,
        "ma_slow": 20,
        "use_rsi": True,
        "rsi_period": 14,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
    },
    "scan": {"poll_interval_minutes": 60, "history_days": 120},
    "notify": {"log_file": "signals.log"},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, raw)
    env = str(cfg["trade"].get("trade_env", "SIMULATE")).upper()
    if env not in ("SIMULATE", "REAL"):
        raise ValueError(f"trade.trade_env must be SIMULATE or REAL, got {env!r}")
    cfg["trade"]["trade_env"] = env
    if not cfg["symbols"]:
        raise ValueError("config.symbols is empty — add tickers like US.VOO")
    # Never read the trade password from the file. Env var only.
    cfg["trade"]["password"] = os.environ.get("MOOMOO_TRADE_PWD")
    return cfg
