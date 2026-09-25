"""Tests for the conviction layer (insider veto + short-interest context)."""
import pytest

import bot.conviction as conviction
import bot.insider as insider_mod
import bot.shortinterest as shortinterest_mod


@pytest.fixture
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(conviction, "CACHE_DIR", tmp_path)


def _cfg(**kw):
    base = {"window_days": 90, "veto_on_net_selling": True,
            "min_net_sell_usd": 1_000_000}
    base.update(kw)
    return {"insider": base}  # check_conviction takes the breakout cfg


def _insider(net, buys=100_000.0, n_buys=2, n_sells=8):
    sells = buys - net
    return {"ticker": "MSFT", "cik": 789019, "window_days": 90,
            "asof": "2026-09-24", "buy_value": buys, "sell_value": sells,
            "net_value": net, "n_buys": n_buys, "n_sells": n_sells,
            "filings_scanned": 10}


def _short():
    return {"ticker": "MSFT", "short_interest": 67_346_414,
            "avg_daily_volume": 18_052_501, "days_to_cover": 3.73,
            "short_pct_float": 0.0, "settlement_date": "2026-09-15",
            "source": "nasdaq"}


def test_veto_on_material_net_selling(_cache, monkeypatch):
    monkeypatch.setattr(insider_mod, "get_insider_summary",
                        lambda t, window_days=90: _insider(-5_000_000.0))
    monkeypatch.setattr(shortinterest_mod, "get_short_interest",
                        lambda t: _short())
    r = conviction.check_conviction("US.MSFT", _cfg())
    assert r["vetoed"] is True
    assert "net selling $5,000,000" in r["veto_reason"]
    assert r["details"]["insider"]["net_usd"] == -5_000_000.0
    assert r["details"]["short_interest"]["source"] == "nasdaq"


def test_no_veto_on_net_buying(_cache, monkeypatch):
    monkeypatch.setattr(insider_mod, "get_insider_summary",
                        lambda t, window_days=90: _insider(2_000_000.0,
                                                          buys=3_000_000.0,
                                                          n_buys=5, n_sells=1))
    monkeypatch.setattr(shortinterest_mod, "get_short_interest",
                        lambda t: _short())
    r = conviction.check_conviction("US.MSFT", _cfg())
    assert r["vetoed"] is False
    assert r["details"]["insider"]["n_buys"] == 5


def test_small_net_selling_below_threshold_no_veto(_cache, monkeypatch):
    monkeypatch.setattr(insider_mod, "get_insider_summary",
                        lambda t, window_days=90: _insider(-500_000.0))
    monkeypatch.setattr(shortinterest_mod, "get_short_interest",
                        lambda t: _short())
    r = conviction.check_conviction("US.MSFT", _cfg())
    assert r["vetoed"] is False  # routine diversification, not a veto


def test_veto_disabled_by_config(_cache, monkeypatch):
    monkeypatch.setattr(insider_mod, "get_insider_summary",
                        lambda t, window_days=90: _insider(-9_000_000.0))
    monkeypatch.setattr(shortinterest_mod, "get_short_interest",
                        lambda t: _short())
    r = conviction.check_conviction("US.MSFT",
                                    _cfg(veto_on_net_selling=False))
    assert r["vetoed"] is False


def test_fail_open_when_sources_down(_cache, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network blocked")
    monkeypatch.setattr(insider_mod, "get_insider_summary", _boom)
    monkeypatch.setattr(shortinterest_mod, "get_short_interest", _boom)
    r = conviction.check_conviction("US.MSFT", _cfg())
    assert r["vetoed"] is False  # outage must never suppress a signal
    assert len(r["notes"]) == 2
    assert r["details"] == {}


def test_results_cached(_cache, monkeypatch, tmp_path):
    calls = {"n": 0}

    def _fake_insider(t, window_days=90):
        calls["n"] += 1
        return _insider(1_000_000.0, buys=1_500_000.0, n_buys=3, n_sells=1)

    monkeypatch.setattr(insider_mod, "get_insider_summary", _fake_insider)
    monkeypatch.setattr(shortinterest_mod, "get_short_interest",
                        lambda t: _short())
    conviction.check_conviction("US.MSFT", _cfg())
    conviction.check_conviction("US.MSFT", _cfg())
    assert calls["n"] == 1  # second call served from disk cache
