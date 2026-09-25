# moomoo-trader

Signal scanner on the moomoo/Futu OpenAPI. It scans a watchlist of US tickers,
detects **MA golden/death cross** and **RSI zone-entry** signals on daily bars,
and prints/logs a ticket for each signal.

**Read-only by design: this program cannot place orders.** There is no trading
code in it at all — no order API calls, no trade password, no paper-trading
mode. It finds opportunities; what you do with a ticket (e.g. placing an
order yourself in the moomoo app) happens entirely outside this program.

## How it works

```
OpenD (moomoo gateway, :11111) ──K-lines──▶ bot scans watchlist
                                            ──▶ signal ticket printed + logged
```

* Signals fire on the **last closed daily bar only** — no repainting.
* MA: fast 5 / slow 20 golden/death cross.
* RSI(14): bullish when it crosses **down** through 30 (enters oversold),
  bearish when it crosses **up** through 70 (enters overbought).
* Both strategies can fire on the same bar (even in opposite directions);
  each gets its own ticket.

## Setup

### 1. moomoo account + API access

In the moomoo app: **Me → Settings → OpenAPI**, complete the questionnaire
assessment and agreement confirmation (required once).

### 2. OpenD

Full steps: [`OPEND_SETUP.md`](OPEND_SETUP.md). Short version:

1. Download: `https://www.moomoo.com/download/fetch-lasted-link?name=opend-ubuntu`
   (use a browser User-Agent — plain curl gets a 403).
2. Extract, `cd` into the versioned dir, run `./OpenD`.
3. Log in at the `Please enter account` / `Please enter password` prompt
   (moomoo ID, phone, or email). First login may need the app for verification.
4. Leave it running — the bot connects to `127.0.0.1:11111`.

### 3. Bot

```bash
git clone <this-repo> && cd moomoo-trader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit symbols / params
.venv/bin/python -m bot.main --dry-run   # sanity check, no OpenD needed
.venv/bin/python -m bot.main --once      # one live scan (needs logged-in OpenD)
.venv/bin/python -m bot.main             # loop every poll_interval_minutes
```

## What it cannot do

* Place, modify, or cancel orders — the code to do so does not exist here.
* Touch your positions, account balance, or trade password (it never asks for one).
* Trade by itself, on a schedule or otherwise. The loop only re-scans and prints.

## Configuration

`config.yaml` (copy of `config.example.yaml`): OpenD host/port, watchlist
(`US.`-prefixed tickers), strategy params, scan interval, log file.
`config.yaml` is gitignored — never commit it.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

11 tests cover: golden/death cross detection, no false positives, no signal on
the unclosed bar (no repainting), RSI oversold→bullish / overbought→bearish
entries, no repeat signal while RSI sits inside a zone, and short-history
safety.

## Project layout

```
bot/
  main.py      scan loop, CLI (--once/--dry-run); prints tickets only
  signals.py   pure MA/RSI logic + closed-bar handling (unit-tested)
  data.py      K-line fetch via futu-api QuoteContext (quotes only)
  notify.py    ticket formatting + JSON-lines signal log
  config.py    YAML config loading
tests/test_signals.py
config.example.yaml   OPEND_SETUP.md   README.md
```

## Installing on another machine

Source + config template are meant to be portable:

1. `git clone` this repo on the new machine.
2. `pip install -r requirements.txt` (Python 3.10+).
3. Download OpenD for that platform from
   https://www.moomoo.com/download/OpenAPI, run it, log in once.
4. Copy `config.example.yaml` → `config.yaml`,
   run `python -m bot.main --dry-run` to verify, then scan live.

## Status / not yet verified

Live quote/K-line fetching needs a **logged-in** OpenD, which needs your real
moomoo credentials — deliberately not done here.
