"""Tiny JSON store for the breakout strategy's live positions.

Shape:
    {"positions": {symbol: {"entry_date", "entry_price", "peak"}},
     "last_exit": {symbol: "YYYY-MM-DD"}}

Positions are only read/written by the live scanner (bot.main). The backtest
keeps its own in-memory state. The file is runtime state, not config.
"""

from __future__ import annotations

import json
import os


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {"positions": {}, "last_exit": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"positions": {}, "last_exit": {}}
    data.setdefault("positions", {})
    data.setdefault("last_exit", {})
    return data


def save(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
