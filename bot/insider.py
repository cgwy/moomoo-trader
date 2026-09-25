"""Insider trading summary from SEC EDGAR Form 4 filings.

Free, no auth, no API key. Pipeline:

1. Ticker -> CIK via https://www.sec.gov/files/company_tickers.json
   (cached locally, refreshed when older than 30 days).
2. Recent Form 4 filings via
   https://data.sec.gov/submissions/CIK{cik:0>10}.json ("recent" block).
3. For each Form 4 (newest first, capped at ~40): fetch the filing's
   index.json, find the primary Form 4 XML document, fetch and parse it.
   Keep only officer/director open-market transactions (code P/S) in
   Common Stock within the trailing window.

SEC requires a descriptive User-Agent on every request; we identify as
"moomoo-trader/1.0 personal-research" and stay well under 10 req/s.
"""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

_UA = "moomoo-trader/1.0 personal-research"
_HEADERS = {"User-Agent": _UA}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".cache",
    "company_tickers.json")
_CACHE_TTL_S = 30 * 86400
_MAX_FILINGS = 40
_FETCH_PAUSE_S = 0.15


# ------------------------------------------------------------- ticker -> CIK

_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def _refresh_ticker_cache() -> bool:
    """Download company_tickers.json into the cache. Returns True on success."""
    try:
        resp = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return False
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        f.write(resp.text)
    return True


def _cik_from_cache(ticker: str) -> int | None:
    if not os.path.exists(_CACHE_PATH):
        return None
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    want = ticker.upper()
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() == want:
            return int(entry["cik_str"])
    return None


def _cik_via_efts(ticker: str) -> int | None:
    """Fallback ticker -> CIK via the EDGAR full-text search API.

    Used only when www.sec.gov is unreachable (e.g. rate-limited for this
    network) and no cache exists. Parses display names like
    "MICROSOFT CORP  (MSFT)  (CIK 0000789019)".
    """
    import re

    try:
        resp = requests.get(
            _EFTS_SEARCH_URL,
            params={"q": f'"{ticker.upper()}"', "forms": "4"},
            headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return None
    hits = resp.json().get("hits", {}).get("hits", [])
    want = f"({ticker.upper()})"
    for hit in hits:
        for name in (hit.get("_source", {}).get("display_names") or []):
            if want not in name:
                continue
            m = re.search(r"\(CIK\s+0*(\d+)\)", name)
            if m:
                return int(m.group(1))
    return None


def _ticker_to_cik(ticker: str) -> int:
    stale = True
    if os.path.exists(_CACHE_PATH):
        stale = time.time() - os.path.getmtime(_CACHE_PATH) > _CACHE_TTL_S
    if stale and not _refresh_ticker_cache() and not os.path.exists(_CACHE_PATH):
        # Download failed and there is no cache at all: fall back to EFTS.
        cik = _cik_via_efts(ticker)
        if cik is None:
            raise RuntimeError(
                f"cannot resolve CIK for {ticker!r}: SEC download blocked "
                "and no cached ticker map available")
        return cik
    cik = _cik_from_cache(ticker)
    if cik is None:
        # Ticker not in (possibly stale) cache: try one fresh download, then
        # EFTS, before giving up.
        if _refresh_ticker_cache():
            cik = _cik_from_cache(ticker)
        if cik is None:
            cik = _cik_via_efts(ticker)
        if cik is None:
            raise RuntimeError(f"ticker {ticker!r} not found in SEC company_tickers.json")
    return cik


# ------------------------------------------------------- recent Form 4 list

def _recent_form4(cik: int, cutoff: date) -> list[tuple[str, str]]:
    """(accession_number, primary_document) for Form 4s filed since cutoff."""
    resp = requests.get(_SUBMISSIONS_URL.format(cik=cik),
                        headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    recent = resp.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primaries = recent.get("primaryDocument", [])
    out: list[tuple[str, str]] = []
    for i in range(len(forms)):
        if forms[i] != "4":
            continue
        try:
            fdate = date.fromisoformat(filing_dates[i])
        except (ValueError, IndexError):
            continue
        if fdate >= cutoff:
            primary = primaries[i] if i < len(primaries) else ""
            out.append((accessions[i], primary))
    return out


# ------------------------------------------------------------ filing XML doc

def _fetch_form4_xml(cik: int, accession: str, primary_doc: str) -> str:
    """Fetch a filing's primary Form 4 XML.

    Tries the primary-document path from the submissions feed directly first
    (it often lives in a subdirectory like ``xslF345X06/form4.xml``), then
    falls back to index.json discovery. Only returns content that actually
    looks like an ownership document.
    """
    nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}"
    urls: list[str] = []
    if primary_doc:
        urls.append(f"{base}/{primary_doc}")
    try:
        resp = requests.get(base + "/index.json", headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("directory", {}).get("item", [])
        for it in items:
            name = str(it.get("name", ""))
            if name.lower().endswith(".xml") and f"{base}/{name}" not in urls:
                urls.append(f"{base}/{name}")
    except Exception:
        pass  # index.json is only a backup; the direct path may still work
    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=30)
        except Exception:
            continue
        if resp.status_code == 200 and "ownershipDocument" in resp.text:
            return resp.text
    raise RuntimeError(f"no Form 4 XML doc retrievable for filing {accession}")


# ------------------------------------------------------------------ XML parse

def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _value(parent: ET.Element, *path: str) -> str:
    """Follow child tags, then prefer the nested <value> text (Form 4 style)."""
    el: ET.Element | None = parent
    for p in path:
        if el is None:
            return ""
        el = el.find(p)
    if el is None:
        return ""
    v = el.find("value")
    return _text(v if v is not None else el)


def _is_officer_or_director(root: ET.Element) -> bool:
    for owner in root.findall("reportingOwner"):
        rel = owner.find("reportingOwnerRelationship")
        if rel is None:
            continue
        if (_text(rel.find("isOfficer")).lower() == "true"
                or _text(rel.find("isDirector")).lower() == "true"):
            return True
    return False


def _parse_transactions(xml_text: str, cutoff: date,
                        today: date) -> tuple[float, float, int, int]:
    """(buy_value, sell_value, n_buys, n_sells) from one Form 4 XML."""
    root = ET.fromstring(xml_text)
    _strip_namespaces(root)
    if not _is_officer_or_director(root):
        return 0.0, 0.0, 0, 0
    buy_value = sell_value = 0.0
    n_buys = n_sells = 0
    table = root.find("nonDerivativeTable")
    if table is None:
        return 0.0, 0.0, 0, 0
    for txn in table.findall("nonDerivativeTransaction"):
        if "common stock" not in _value(txn, "securityTitle").lower():
            continue
        code = _value(txn, "transactionCoding", "transactionCode").upper()
        if code not in ("P", "S"):
            continue
        try:
            tdate = date.fromisoformat(_value(txn, "transactionDate"))
        except ValueError:
            continue
        if tdate < cutoff or tdate > today:
            continue
        try:
            shares = float(_value(txn, "transactionAmounts",
                                  "transactionShares").replace(",", ""))
            price = float(_value(txn, "transactionAmounts",
                                 "transactionPricePerShare").replace(",", ""))
        except ValueError:
            continue
        if shares <= 0 or price <= 0:
            continue
        value = shares * price
        if code == "P":
            buy_value += value
            n_buys += 1
        else:
            sell_value += value
            n_sells += 1
    return buy_value, sell_value, n_buys, n_sells


# ------------------------------------------------------------------- public

def get_insider_summary(ticker: str, window_days: int = 90) -> dict:
    """Net officer/director open-market buying vs selling, trailing window.

    Returns {"ticker","cik","window_days","asof","buy_value","sell_value",
    "net_value","n_buys","n_sells","filings_scanned"} — floats/ints, never None.
    """
    today = date.today()
    cutoff = today - timedelta(days=window_days)
    cik = _ticker_to_cik(ticker)
    filings = _recent_form4(cik, cutoff)[:_MAX_FILINGS]
    buy_value = sell_value = 0.0
    n_buys = n_sells = scanned = 0
    fetch_errors = 0
    for accession, primary_doc in filings:
        time.sleep(_FETCH_PAUSE_S)
        try:
            xml_text = _fetch_form4_xml(cik, accession, primary_doc)
            b, s, nb, ns = _parse_transactions(xml_text, cutoff, today)
        except Exception:
            fetch_errors += 1
            continue  # one bad filing must not kill the whole summary
        scanned += 1
        buy_value += b
        sell_value += s
        n_buys += nb
        n_sells += ns
    if filings and scanned == 0:
        raise RuntimeError(
            f"SEC EDGAR would not serve any Form 4 documents for {ticker} "
            f"({fetch_errors} fetch failures — likely SEC rate-limiting this "
            "network). No data was fabricated; try again later.")
    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "window_days": window_days,
        "asof": today.isoformat(),
        "buy_value": round(buy_value, 2),
        "sell_value": round(sell_value, 2),
        "net_value": round(buy_value - sell_value, 2),
        "n_buys": n_buys,
        "n_sells": n_sells,
        "filings_scanned": scanned,
    }


if __name__ == "__main__":
    for t in ("MSFT", "AAPL"):
        print(json.dumps(get_insider_summary(t), indent=2))
