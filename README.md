# Apple Store pickup watcher

Watches in-store pickup availability for one Apple product at the stores you
pick (default: **Woodfield, Schaumburg**). When a store has it, the bot:

1. alerts you: phone push via [ntfy](https://ntfy.sh), Discord, a desktop
   pop-up and a beep
2. optionally drives checkout for **pickup** in a real Chrome window: Add to
   Bag → Check Out → "I'll pick it up" → Woodfield → earliest time → payment →
   review. By default it stops on **Place Your Order** so you make the final
   click. It places the order itself only if you set `place_order = true`.

It checks the same JSON endpoint (`/shop/fulfillment-messages`) that the
product page calls to show its "Pickup: …" line, so each check costs Apple one
small request, the same as a page refresh.

## Setup (once, before the 23rd)

Requires Python 3.11+ and Google Chrome.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m playwright install chromium   # fallback browser if Chrome isn't found

copy config.example.toml config.toml    # macOS/Linux: cp
```

1. **Sign in once:** `python bot.py setup` opens the bot's own Chrome profile.
   Sign in to your Apple ID. Confirm that a card is saved to your account, and
   **empty your bag**, because checkout buys everything in it.
2. **Find the part number:** `python bot.py discover` loads `product_url` and
   prints the part number (e.g. `MABC4LL/A`) the page checks pickup for. Put it
   in `part_number`.
3. **Check the store list:** `python bot.py stores` prints every store near
   `zip_code` with its current status, and marks the stores you chose with `*`.
   Make sure Woodfield is marked. You can add backup stores to `stores` in
   priority order.
4. **Set up phone alerts:** install the ntfy app, subscribe to a long random
   topic name (anyone who knows the name can read it), and put the same name
   in `notify.ntfy_topic`. Then run `python bot.py test-notify`.
5. **If Apple asks for your card's security code at checkout**, provide it
   through an environment variable instead of the config file:
   `set APPLE_CVV=123` (PowerShell: `$env:APPLE_CVV="123"`; macOS/Linux:
   `export APPLE_CVV=123`).

### Rehearse before launch night (strongly recommended)

Apple's checkout pages can't be tested ahead of a launch. The checkout steps
use text-based matching with fallbacks, but they have only been tested against
a mock. Two rehearsals will show whether they work for you:

* **Offline:** `python tests/mock_apple.py 8765`, then in a second terminal:
  `APPLE_CVV=123 python bot.py -c tests/mock_config.toml watch --now`
* **On apple.com:** point a copy of your config at something that is in
  stock for pickup at Woodfield today (a cable or a case), keep
  `place_order = false`, and run `python bot.py -c test.toml watch --now`.
  It should get all the way to the Place Your Order page. Then empty your bag.

## Launch night

```bash
python bot.py watch
```

With `start_at = "2026-10-23T00:00"` you can start it early. It waits until
that time and then begins checking. Use `--now` to skip the wait and `--once`
for a single check. Leave the window open and keep the computer awake: turn
off sleep, and on a laptop plug it in. Everything is also logged to `bot.log`.

The product page currently says pickup opens on **10.24**. Until then, expect
`unavailable` lines. That's fine.

When pickup shows up:

* `checkout.enabled = false`: you get an alert, the product page opens, and
  you check out yourself. You get another alert every 2 minutes while it stays
  available.
* `checkout.enabled = true, place_order = false` (the default): the bot stops
  on Place Your Order and pushes **"PLACE ORDER NOW"**.
* `place_order = true`: the bot places the order and pushes **"ORDER PLACED"**.

If any step fails (the page changed, Apple wants you to sign in again, a
security code is needed and missing, and so on), the bot stops, pushes
**"Finish checkout by hand NOW"**, and leaves the browser on that page with the
phone already in your bag. If Apple asks you to sign in during checkout, the
bot waits up to 5 minutes for you to do it and then continues.

## Not getting blocked (one home IP, no proxies)

What the bot does:

* **About one check every 12 s** (randomized ±30%), from a single real browser
  tab. That's about 300 small requests an hour, similar to one person
  refreshing a page. Don't go below about 8 s, and don't run two copies.
* **Backs off automatically** on 403/429/503 or an HTML "access denied" page:
  waits 1, 2, 4… minutes, up to 15. It alerts you if this happens 3 times in a
  row.
* **`engine = "browser"`** (the default) runs checks from a real Chrome
  session that is signed in to your Apple ID. That is far less likely to be
  throttled than a script client, and it's already warm when checkout starts.
  `engine = "http"` is lighter but more likely to get 403s.

What to expect: an over-eager poller usually gets a **temporary** block on
apple.com for that IP (minutes to hours), not an Apple ID ban. The real cost is
that a block also locks *you* out during the drop, so a faster interval is
worse, not better. If you do get blocked, switching the computer to your
phone's hotspot gives you a different IP of your own.

The bot does not use proxies, fake browser fingerprints, or solve CAPTCHAs. If
Apple shows a challenge, finish that step yourself in the open window. It's
meant for buying your own phone.

## Config reference

See `config.example.toml`. Every key is commented there.

## Finding the part number manually

If `discover` comes up empty: open the product page in Chrome, press F12 →
Network, filter by `fulfillment`, and reload. The request URL contains
`parts.0=XXXXXLL%2FA`. That value, with `%2F` changed to `/`, is the part
number.

## Tests

```bash
pip install pytest && python -m pytest -q
```
