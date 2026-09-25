# OpenD Setup (Linux / Ubuntu)

## Download

- **Exact URL used:** `https://www.moomoo.com/download/fetch-lasted-link?name=opend-ubuntu`
- **Version downloaded:** 10.11.7108 (released Sep 17, 2026 per
  https://www.moomoo.com/download/OpenAPI ; binary reports
  `10.11.7108(20260916134500)`)
- **Note:** plain `curl` without a browser User-Agent gets `403 - Operations too
  frequent` from moomoo's CDN. This worked:
  ```bash
  UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
  curl -sL -A "$UA" -o MoomooOpenD.tar.gz \
    "https://www.moomoo.com/download/fetch-lasted-link?name=opend-ubuntu"
  ```

## Extract

```bash
mkdir -p ~/moomoo-opend && tar --no-same-owner -xzf MoomooOpenD.tar.gz -C ~/moomoo-opend
# Binary lives at:
#   moomoo_OpenD_10.11.7108_Ubuntu18.04/moomoo_OpenD_10.11.7108_Ubuntu18.04/OpenD
# (--no-same-owner avoids "Cannot change ownership" errors when not root.
#  Skipping the F3CChart/ indicator scripts and the GUI .AppImage saves ~400MB.)
```

A copy is kept at `~/workspace/moomoo-trader/opend/` on this VM (gitignored,
not part of the repo).

## Configure

Edit `OpenD.xml` next to the binary. Defaults are fine for local use:

| Item | Default | Notes |
|---|---|---|
| `ip` | `127.0.0.1` | API listen address |
| `api_port` | `11111` | API protocol port — the bot connects here |
| `lang` | `en` | |

**v10.10+ removed `account`/`password` from `OpenD.xml`.** Do not look for them
there — login is now interactive (below).

## Start

```bash
cd moomoo_OpenD_10.11.7108_Ubuntu18.04/moomoo_OpenD_10.11.7108_Ubuntu18.04
./OpenD
```

Expected output (verified on this VM):

```
moomoo OpenD version info: 10.11.7108(20260916134500)
moomoo OpenD is running
Configuration file loaded successfully
Server started
API Listening Address: 127.0.0.1:11111
API RSA Enabled: No
```

Keep it running in the background (`nohup ./OpenD &`, tmux, or systemd). The
bot connects to `127.0.0.1:11111`.

## Headless login (verified via PTY on this VM)

When `./OpenD` runs attached to a terminal, after `API RSA Enabled: No` it
prompts:

```
Please enter account
Please enter password
```

- **Account:** your moomoo ID, or the phone number / email you registered with.
- **Password:** your moomoo login password.
- Non-interactive alternative (from `./OpenD --help`):
  `./OpenD login_account=<your moomoo ID / phone / email>`
  (then complete the password step at the prompt; `login_by_remember` /
  `login_region` params also exist).
- **First login:** you must complete the questionnaire assessment and agreement
  confirmation in the moomoo app before the API works — see
  https://openapi.futunn.com/futu-api-doc/intro/authority.html

⚠️ **Without a logged-in account, API calls hang/timeout** — the server binds
the port but the SDK never gets a response. If the bot seems stuck connecting,
OpenD is almost certainly not logged in. (Observed, not guessed.)

**Not verified** (needs your real account, deliberately not attempted):
the actual password handshake, 2FA/device-verification-code step if triggered,
and session persistence across restarts (`AppData.dat` next to the binary
likely caches it — use `login_by_remember` or just log in again).

## GUI alternative

The tarball also contains a `.deb` GUI installer
(`moomoo_OpenD-GUI_*_Ubuntu*.deb`). If the terminal login gives trouble,
install the GUI once, log in there, then switch back to the command-line
binary — they share the same API port.
