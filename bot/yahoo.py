"""Daily bars from the Yahoo Finance chart API.

No auth, no API key, no login. Same bar shape as data.QuoteClient so the two
sources are interchangeable:
    {"date", "open", "high", "low", "close", "volume"}  (oldest -> newest)

"close" is the split/dividend-adjusted close (like futu's QFQ), so indicator
math doesn't jump on corporate actions.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_HEADERS = {
    # Yahoo rejects requests without a browser-like User-Agent.
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
}


def _range_for(history_days: int) -> str:
    if history_days <= 60:
        return "3mo"
    if history_days <= 160:
        return "6mo"
    if history_days <= 400:
        return "1y"
    return "2y"


class YahooClient:
    def get_daily_klines(self, symbol: str, history_days: int = 120) -> list[dict]:
        # Config symbols are futu-style ("US.VOO"); Yahoo wants "VOO".
        ticker = symbol.split(".", 1)[-1].upper()
        url = _CHART_URL.format(ticker=ticker)
        resp = requests.get(
            url,
            params={"interval": "1d", "range": _range_for(history_days)},
            headers=_HEADERS,
            timeout=20,
        )
        time.sleep(0.5)  # be polite between symbols
        if resp.status_code == 429:
            raise RuntimeError(f"Yahoo chart({ticker}): rate-limited (429), try again later")
        resp.raise_for_status()
        payload = resp.json()
        results = (payload.get("chart") or {}).get("result") or []
        if not results:
            err = (payload.get("chart") or {}).get("error") or {}
            raise RuntimeError(
                f"Yahoo chart({ticker}): {err.get('description', 'no result')}")
        res = results[0]
        timestamps = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        bars = []
        for i, ts in enumerate(timestamps):
            px = (adj[i] if adj and i < len(adj) and adj[i] is not None
                  else closes[i] if i < len(closes) else None)
            if px is None:
                continue
            bars.append({
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": float(opens[i]) if i < len(opens) and opens[i] is not None else px,
                "high": float(highs[i]) if i < len(highs) and highs[i] is not None else px,
                "low": float(lows[i]) if i < len(lows) and lows[i] is not None else px,
                "close": float(px),
                "volume": int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0,
            })
        if not bars:
            raise RuntimeError(f"Yahoo chart({ticker}): no usable bars returned")
        return bars

    def close(self):
        pass
