"""Signal tickets: pretty console print + JSON-lines log.

Tickets are informational only: what fired, where, and the indicator values.
There is no order suggestion, quantity, or price target — this program cannot
trade and does not tell you how to trade.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

TYPE_LABEL = {
    "ma_golden_cross": "MA GOLDEN CROSS (fast crossed above slow)",
    "ma_death_cross": "MA DEATH CROSS (fast crossed below slow)",
    "rsi_oversold": "RSI ENTERED OVERSOLD (crossed down through line)",
    "rsi_overbought": "RSI ENTERED OVERBOUGHT (crossed up through line)",
}

DIRECTION_EMOJI = {"bullish": "🟢", "bearish": "🔴"}


def format_ticket(signal: dict) -> str:
    d = signal.get("details", {})
    lines = [
        "┌" + "─" * 58 + "┐",
        f"│ SIGNAL  {DIRECTION_EMOJI.get(signal['direction'], '')} "
        f"{TYPE_LABEL.get(signal['type'], signal['type']):<44}│",
        "├" + "─" * 58 + "┤",
        f"│ symbol    : {signal['symbol']:<43}│",
        f"│ direction : {signal['direction']:<43}│",
        f"│ bar_date  : {signal['bar_date']:<43}│",
        f"│ close     : {d.get('close', '?'):<43}│",
    ]
    if signal["type"].startswith("ma_"):
        lines.append(f"│ MA fast/slow: {d.get('ma_fast')} / {d.get('ma_slow')}"
                     f" (prev {d.get('ma_fast_prev')} / {d.get('ma_slow_prev')})".ljust(59) + "│")
    if signal["type"].startswith("rsi_"):
        lines.append(f"│ RSI({d.get('rsi_period')}): {d.get('rsi')} (prev {d.get('rsi_prev')})".ljust(59) + "│")
    lines.append("└" + "─" * 58 + "┘")
    return "\n".join(lines)


def emit(signal: dict, log_file: str = "signals.log") -> None:
    """Print the ticket and append a JSON line to the log."""
    print(format_ticket(signal))
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **signal,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
