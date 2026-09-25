# moomoo-trader

Semi-automatic trading assistant on the moomoo/Futu OpenAPI. It scans a
watchlist of US tickers, detects **MA golden/death cross** and **RSI zone-entry**
signals on daily bars, prints a ticket for each signal — and **you** type
`confirm` before anything is ordered. Nothing trades by itself.

## How it works

```
OpenD (moomoo gateway, :11111) ──K-lines──▶ bot scans watchlist
                                            ──▶ signal ticket printed + logged
                                            ──▶ you type 'confirm' ──▶ limit order
```

* Signals fire on the **last closed daily bar only** — no repainting.
* MA: fast 5 / slow 20 golden/death cross.
* RSI(14): bullish when it crosses **down** through 30 (enters oversold),
  bearish when it crosses **up** through 70 (enters overbought).
* Both strategies can fire on the same bar (even in opposite directions);
  each ticket is confirmed separately — you decide.

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
export MOOMOO_TRADE_PWD='...'        # trade password: env var ONLY, never in files
.venv/bin/python -m bot.main --dry-run   # sanity check, no OpenD needed
.venv/bin/python -m bot.main --once      # one live scan (needs logged-in OpenD)
.venv/bin/python -m bot.main             # loop every poll_interval_minutes
```

## Safety model

* Default `trade_env: SIMULATE` — paper trading only.
* Every order needs a typed `confirm` at its own prompt. Anything else skips.
* `trade_env: REAL` additionally requires typing `TRADE REAL` at startup, and
  `Executor` refuses REAL orders without that explicit arming.
* Trade password only via `MOOMOO_TRADE_PWD`. `config.yaml` is gitignored.

## Configuration

`config.yaml` (copy of `config.example.yaml`): OpenD host/port, trade env,
watchlist (`US.`-prefixed tickers), strategy params, scan interval, log file.

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
  main.py      scan loop, CLI (--once/--dry-run), confirmation flow
  signals.py   pure MA/RSI logic + closed-bar handling (unit-tested)
  data.py      K-line fetch via futu-api QuoteContext
  executor.py  order placement with REAL-money guards
  notify.py    ticket formatting + JSON-lines signal log
  config.py    YAML config; password from env only
tests/test_signals.py
config.example.yaml   OPEND_SETUP.md   README.md
```

## Installing on another machine

Source + config template are meant to be portable:

1. `git clone` this repo on the new machine.
2. `pip install -r requirements.txt` (Python 3.10+).
3. Download OpenD for that platform from
   https://www.moomoo.com/download/OpenAPI, run it, log in once.
4. Copy `config.example.yaml` → `config.yaml`, set `MOOMOO_TRADE_PWD`,
   run `python -m bot.main --dry-run` to verify, then go live.

## Status / not yet verified

Live quote/K-line fetching and order placement need a **logged-in** OpenD,
which needs your real moomoo credentials — deliberately not done here.
First live run: use `--once` with `SIMULATE` and watch the tickets.
