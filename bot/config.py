"""Config loading."""

from __future__ import annotations

import yaml

DEFAULTS = {
    # "yahoo" = Yahoo Finance chart API (no login). "opend" = local OpenD.
    "data_source": "yahoo",
    "opend": {"host": "127.0.0.1", "port": 11111},
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
    src = str(cfg.get("data_source", "yahoo")).lower()
    if src not in ("yahoo", "opend"):
        raise ValueError(f"data_source must be 'yahoo' or 'opend', got {src!r}")
    cfg["data_source"] = src
    if not cfg["symbols"]:
        raise ValueError("config.symbols is empty — add tickers like US.VOO")
    return cfg
