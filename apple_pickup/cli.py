from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import datetime

from . import availability, config
from .engines import Blocked, make_engine
from .notify import Notifier

log = logging.getLogger("apple_pickup")


def setup_logging(verbose: bool):
    fmt = "%(asctime)s %(levelname)-7s %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler("bot.log", encoding="utf-8")]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=fmt, datefmt="%H:%M:%S", handlers=handlers)


def require_part(cfg):
    if not cfg.part_number:
        sys.exit("part_number is empty in your config. Run `python bot.py discover` first.")


# ---------------------------------------------------------------- commands


def cmd_setup(cfg, args):
    """Open the bot's browser profile so you can sign in to your Apple ID once."""
    from .browser import open_context

    pw, ctx = open_context(cfg.checkout)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(f"{cfg.apple_base}/shop/bag")
    print(
        "\nIn the browser window:\n"
        "  1. Sign in to your Apple ID (Account > Sign In).\n"
        "  2. Make sure a payment card is saved to your Apple account.\n"
        "  3. Make sure your bag is EMPTY (checkout buys everything in it).\n"
    )
    input("Press Enter here when done... ")
    ctx.close()
    pw.stop()


def cmd_discover(cfg, args):
    """Find the part number by watching what the product page itself requests."""
    from .browser import open_context

    found: list[str] = []

    def on_request(req):
        if availability.FULFILLMENT_PATH in req.url or "pickup-message" in req.url:
            for part in availability.find_part_numbers(req.url.replace("%2F", "/")):
                if part not in found:
                    found.append(part)

    pw, ctx = open_context(cfg.checkout, headless=args.headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", on_request)
        page.goto(cfg.product_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(8000)
        html_parts = availability.find_part_numbers(page.content())
    finally:
        ctx.close()
        pw.stop()

    if found:
        print("Part number(s) the page checked pickup for (use the first):")
        for p in found:
            print(f"  {p}")
    elif html_parts:
        print("No availability request seen; part numbers found in the page HTML:")
        for p in html_parts[:15]:
            print(f"  {p}")
        print("Pick the one for your exact model/color/capacity (see README for how to confirm).")
    else:
        print("No part numbers found. See README > 'Finding the part number manually'.")


def cmd_stores(cfg, args):
    """One request: show pickup status at every store near your ZIP."""
    require_part(cfg)
    engine = make_engine(cfg)
    try:
        data = engine.fetch(availability.build_url(cfg.apple_base, cfg.part_number, cfg.zip_code))
    finally:
        engine.close()
    stores = availability.parse_stores(data, cfg.part_number)
    if not stores:
        print("No stores in the response (wrong part number, or pickup not offered yet).")
    for s in stores:
        wanted = any(availability.match_store(s, w) for w in cfg.stores)
        print(f"{'*' if wanted else ' '} {s.label():45} {s.display:12} {s.quote}")
    print("\n* = a store from your `stores` list")


def cmd_test_notify(cfg, args):
    Notifier(cfg.notify).send("Test alert", "If you got this, alerts work.", cfg.product_url)


def cmd_watch(cfg, args):
    require_part(cfg)
    notifier = Notifier(cfg.notify)
    if cfg.checkout.enabled and cfg.engine != "browser":
        log.warning("checkout.enabled works best with engine = \"browser\" (already signed in and warm)")

    start = cfg.start_time()
    if start and not args.now:
        while (left := (start - datetime.now()).total_seconds()) > 0:
            log.info("waiting until %s (%.0f min left)", start.isoformat(" ", "minutes"), left / 60)
            time.sleep(min(left, 60))

    url = availability.build_url(cfg.apple_base, cfg.part_number, cfg.zip_code)
    engine = make_engine(cfg)
    notifier.send("Watcher started", f"Watching {', '.join(cfg.stores)} for {cfg.part_number}", urgent=False)

    handed_off = False
    blocks = 0
    was_available = False
    last_alert = 0.0
    try:
        while True:
            try:
                data = engine.fetch(url)
            except Blocked as e:
                blocks += 1
                wait = min(60 * 2 ** (blocks - 1), cfg.max_backoff_seconds)
                log.warning("throttled by Apple (%s); backing off %.0fs", e, wait)
                if blocks == 3:
                    notifier.send("Apple is throttling the watcher", f"Backing off up to {cfg.max_backoff_seconds:.0f}s.", urgent=False)
                time.sleep(wait)
                continue
            except Exception as e:
                log.warning("request failed: %s; retrying in 30s", e)
                time.sleep(30)
                continue
            blocks = 0

            stores = availability.parse_stores(data, cfg.part_number)
            target = availability.pick_target(stores, cfg.stores)
            wanted = [s for s in stores if any(availability.match_store(s, w) for w in cfg.stores)]
            summary = "; ".join(f"{s.name}: {s.display}" for s in wanted) or "target store not in response"
            others = [s.name for s in stores if s.available and s not in wanted]
            log.info("%s%s", summary, f" | also available: {', '.join(others)}" if others else "")

            if target:
                if not was_available or time.monotonic() - last_alert > 120:
                    notifier.send(
                        f"AVAILABLE for pickup at {target.name}!",
                        f"{target.quote or 'Available'} - {cfg.part_number}",
                        cfg.product_url,
                    )
                    last_alert = time.monotonic()
                if cfg.checkout.enabled:
                    handed_off = True
                    _checkout_and_hold(cfg, engine, target, notifier)
                    return
                if not was_available:
                    notifier.open(cfg.product_url)
            was_available = target is not None

            if args.once:
                return
            time.sleep(cfg.interval_seconds * random.uniform(1 - cfg.jitter, 1 + cfg.jitter))
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        if not handed_off:
            engine.close()


def _checkout_and_hold(cfg, engine, store, notifier):
    from .checkout import run_checkout

    page = engine.page()
    pw = ctx = None
    if page is None:
        from .browser import open_context

        engine.close()
        pw, ctx = open_context(cfg.checkout, headless=cfg.checkout.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

    placed = run_checkout(page, cfg, store, notifier)
    log.info("checkout finished: %s", "ORDER PLACED" if placed else "needs you in the browser")
    # Keep the browser open so you can see/finish the order.
    try:
        input("Browser left open. Press Enter to close it and exit... ")
    except (EOFError, KeyboardInterrupt):
        pass
    if ctx is not None:
        ctx.close()
        pw.stop()
    else:
        engine.close()


# ---------------------------------------------------------------- entry


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bot.py", description="Apple Store pickup watcher")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="sign in to Apple ID in the bot's browser profile")
    d = sub.add_parser("discover", help="find the part number for product_url")
    d.add_argument("--headless", action="store_true")
    sub.add_parser("stores", help="show pickup status near your ZIP once")
    sub.add_parser("test-notify", help="send a test alert")
    w = sub.add_parser("watch", help="poll until available, then alert / check out")
    w.add_argument("--once", action="store_true", help="single poll, then exit")
    w.add_argument("--now", action="store_true", help="ignore start_at")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    cfg = config.load(args.config)
    {
        "setup": cmd_setup,
        "discover": cmd_discover,
        "stores": cmd_stores,
        "test-notify": cmd_test_notify,
        "watch": cmd_watch,
    }[args.cmd](cfg, args)
