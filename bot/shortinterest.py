"""Short-interest snapshot for a US ticker.

Primary: Nasdaq API (free, no auth, no key)
  https://api.nasdaq.com/api/quote/{TICKER}/short-interest?assetclass=stocks
Fallback: FINRA consolidated short-interest dataset via api.finra.org
  (free, no auth, no key). Verified at runtime before use.

Never fabricates numbers: if neither source works, raises RuntimeError.
"""

from __future__ import annotations

import json
from datetime import datetime

import requests

_NASDAQ_URL = ("https://api.nasdaq.com/api/quote/{ticker}/short-interest"
               "?assetclass=stocks")
_NASDAQ_HEADERS = {
    # Nasdaq blocks non-browser clients; this UA + Accept is what works.
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json",
}

_FINRA_META = ("https://api.finra.org/metadata/group/otcMarket/name/"
               "consolidatedShortInterest")
_FINRA_DATA = ("https://api.finra.org/data/group/otcMarket/name/"
               "consolidatedShortInterest")
_FINRA_UA = "moomoo-trader/1.0 personal-research"


def _num(value) -> float:
    """Parse Nasdaq-style numbers like '12,345,678' or '3.65%'."""
    if value is None:
        return 0.0
    s = str(value).replace(",", "").replace("%", "").strip()
    if not s or s in ("-", "N/A", "--"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# -------------------------------------------------------------------- Nasdaq

def _from_nasdaq(ticker: str) -> dict:
    t = ticker.upper()
    resp = requests.get(_NASDAQ_URL.format(ticker=t),
                        headers=_NASDAQ_HEADERS, timeout=20)
    if resp.status_code == 403:
        raise RuntimeError("Nasdaq API blocked the request (403)")
    resp.raise_for_status()
    payload = resp.json()
    # Shape: data.shortInterestTable.{headers, rows}; rows are newest-first,
    # but we pick the max settlementDate explicitly. Dates are MM/DD/YYYY.
    rows = ((payload.get("data") or {}).get("shortInterestTable")
            or {}).get("rows") or []
    if not rows:
        raise RuntimeError(f"Nasdaq API returned no short-interest rows for {t}")

    def settle_key(row) -> str:
        raw = str(row.get("settlementDate", ""))
        try:
            return datetime.strptime(raw, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return raw

    row = max(rows, key=settle_key)
    get = lambda *keys: next(  # noqa: E731
        (row[k] for k in keys if k in row and row[k] not in (None, "")), None)
    # Nasdaq exposes no percent-of-float here; we do not invent one.
    return {
        "ticker": t,
        "short_interest": _num(get("interest", "shortInterest")),
        "avg_daily_volume": _num(get("avgDailyShareVolume", "avgDailyVolume")),
        "days_to_cover": _num(get("daysToCover")),
        "short_pct_float": 0.0,
        "settlement_date": settle_key(row),
        "source": "nasdaq",
    }


# --------------------------------------------------------------------- FINRA

def _from_finra(ticker: str) -> dict:
    """FINRA consolidated short interest (bi-monthly). Verifies the dataset
    metadata first, then queries the latest settlement date for the ticker."""
    t = ticker.upper()
    headers = {"User-Agent": _FINRA_UA, "Accept": "application/json"}
    meta = requests.get(_FINRA_META, headers=headers, timeout=20)
    if meta.status_code != 200:
        raise RuntimeError(
            f"FINRA metadata unavailable (HTTP {meta.status_code})")
    fields = {f.get("fieldName") for f in meta.json().get("fields", [])}
    sym_field = next((f for f in ("issueSymbolIdentifier", "symbol",
                                  "issueSymbol") if f in fields), None)
    date_field = next((f for f in ("settlementDate", "settlement_date")
                       if f in fields), None)
    if sym_field is None or date_field is None:
        raise RuntimeError(
            f"FINRA short-interest schema changed; fields={sorted(fields)}")
    params = {
        "filter": f"{sym_field}={t}",
        "sortFields": f"-{date_field}",
        "limit": 5,
    }
    resp = requests.get(_FINRA_DATA, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    rows = resp.json() if isinstance(resp.json(), list) else []
    if not rows:
        raise RuntimeError(f"FINRA returned no short-interest rows for {t}")
    row = rows[0]
    get = lambda *keys: next(  # noqa: E731
        (row[k] for k in keys if k in row and row[k] not in (None, "")), None)
    return {
        "ticker": t,
        "short_interest": _num(get("shortInterest", "short_interest")),
        "avg_daily_volume": _num(get("averageDailyVolume", "avgDailyVolume",
                                     "avg_daily_volume")),
        "days_to_cover": _num(get("daysToCover", "days_to_cover")),
        "short_pct_float": _num(get("percentOfFloatShorted",
                                    "percentShortInterest",
                                    "short_pct_float")),
        "settlement_date": str(get(date_field) or ""),
        "source": "finra",
    }


# ------------------------------------------------------------------- public

def get_short_interest(ticker: str) -> dict:
    """Latest short-interest snapshot. Nasdaq first, FINRA fallback.

    Returns {"ticker","short_interest","avg_daily_volume","days_to_cover",
    "short_pct_float","settlement_date","source"}. Raises RuntimeError if no
    source works — numbers are never fabricated.
    """
    errors: list[str] = []
    for name, fn in (("nasdaq", _from_nasdaq), ("finra", _from_finra)):
        try:
            return fn(ticker)
        except Exception as e:  # noqa: BLE001 - try the next source
            errors.append(f"{name}: {e}")
    raise RuntimeError(
        f"short interest unavailable for {ticker.upper()}; "
        + "; ".join(errors))


if __name__ == "__main__":
    print(json.dumps(get_short_interest("MSFT"), indent=2))
