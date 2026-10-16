"""Best-effort in-store-pickup checkout on apple.com.

Apple changes its checkout markup without notice, so every step tries text/role
locators first and Apple's `data-autom` hooks second. If any step can't be
completed, we STOP, alert you, and leave the browser on that page so you can
finish by hand - the item is already in your bag, so you're still way ahead.

Nothing here solves CAPTCHAs, enters passwords, or hides that it's automation.
"""

from __future__ import annotations

import logging
import os
import re
import time

log = logging.getLogger(__name__)


class StepFailed(Exception):
    pass


def _role(role, pattern):
    rx = re.compile(pattern, re.I)
    return lambda p: p.get_by_role(role, name=rx)


def _css(selector):
    return lambda p: p.locator(selector)


def _text(pattern):
    rx = re.compile(pattern, re.I)
    return lambda p: p.get_by_text(rx)


def _first_visible(page, candidates, exclude=None):
    for make in candidates:
        try:
            loc = make(page)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                if not (el.is_visible() and el.is_enabled()):
                    continue
                if exclude is not None and exclude.search(el.inner_text(timeout=1000)):
                    continue
                return el
        except Exception:
            continue
    return None


def wait_for_any(page, candidates, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        el = _first_visible(page, candidates)
        if el is not None:
            return el
        page.wait_for_timeout(250)
    raise StepFailed(f"could not find {what}")


def click_any(page, candidates, timeout, what):
    el = wait_for_any(page, candidates, timeout, what)
    log.info("checkout: clicking %s", what)
    el.click()
    return el


def click_if_present(page, candidates, what, timeout=2.0):
    try:
        return click_any(page, candidates, timeout, what)
    except StepFailed:
        return None


ADD_TO_BAG = [
    _role("button", r"^\s*add to bag\s*$"),
    _css('[data-autom="add-to-cart"]'),
    _css('button[name="add-to-cart"]'),
]
NO_APPLECARE = [
    _role("radio", r"no applecare"),
    _text(r"^\s*no applecare\+? coverage\s*$"),
    _css('[data-autom="noapplecare"]'),
]
REVIEW_BAG = [
    _role("button", r"^\s*review bag\s*$"),
    _role("link", r"^\s*review bag\s*$"),
    _css('[data-autom="proceed"]'),
]
CHECK_OUT = [
    _css('[data-autom="checkout"]'),
    _css("#shoppingCart\\.actions\\.navCheckout"),
    _role("button", r"^\s*check ?out\s*$"),
]
GUEST = [
    _css('[data-autom="guest-checkout-btn"]'),
    _role("button", r"continue as guest"),
]
PICKUP_OPTION = [
    _role("button", r"i.?ll pick it up"),
    _role("radio", r"pick it up|pickup"),
    _css('[data-autom="fulfillment-pickup-button"]'),
    _text(r"^\s*i.?ll pick it up\s*$"),
]
ZIP_INPUT = [
    _css('[data-autom="bag-storelocator-input"]'),
    _role("textbox", r"zip|postal|location|city"),
    _css('input[name*="location" i], input[name*="zip" i], input[id*="storelocator" i]'),
]
SHOW_STORES = [
    _role("button", r"show (stores|more stores|stores near)"),
    _role("button", r"^\s*(apply|search)\s*$"),
]
PICKUP_TIME_SELECT = [
    _css('[data-autom="pickup-availablewindow-dropdown"]'),
    _css('select[name*="timeslot" i], select[id*="timeslot" i], select[name*="window" i]'),
]
CONTINUE = [
    _css('[data-autom="fulfillment-continue-button"]'),
    _css('[data-autom="pickup-continue-button"]'),
    _css('[data-autom="continue-button-label"]'),
    _role("button", r"^\s*continue to (pickup details|payment|shipping address)\s*$"),
    _role("button", r"^\s*review your order\s*$"),
    _role("button", r"^\s*continue\s*$"),
]
CVV_INPUT = [
    _role("textbox", r"security code|cvv|cvc"),
    _css('input[name*="securityCode" i], input[id*="securityCode" i], input[autocomplete="cc-csc"]'),
]
PLACE_ORDER_RX = re.compile(r"place\s+(your\s+)?order", re.I)
PLACE_ORDER = [
    _role("button", PLACE_ORDER_RX.pattern),
]
ORDER_DONE = [
    _text(r"your order is placed|thank you for your order|order number"),
]


def run_checkout(page, cfg, store, notifier) -> bool:
    """Drive checkout for pickup at `store`. Returns True if the order was placed."""
    t = cfg.checkout.step_timeout_seconds
    step = "start"
    try:
        step = "open product page"
        page.goto(cfg.product_url, wait_until="domcontentloaded", timeout=45_000)
        click_if_present(page, NO_APPLECARE, "No AppleCare option")

        step = "Add to Bag"
        click_any(page, ADD_TO_BAG, t, "Add to Bag")
        # Apple usually shows an add-ons page with "Review Bag" next, sometimes
        # the bag itself. Take whichever appears first; else open the bag.
        try:
            wait_for_any(page, REVIEW_BAG + CHECK_OUT, t, "Review Bag / Check Out")
        except StepFailed:
            page.goto(f"{cfg.apple_base}/shop/bag", wait_until="domcontentloaded")
        if _first_visible(page, CHECK_OUT) is None:
            click_if_present(page, REVIEW_BAG, "Review Bag")

        step = "Check Out"
        click_any(page, CHECK_OUT, t, "Check Out")
        _handle_sign_in(page, cfg, notifier)

        step = "choose pickup"
        click_any(page, PICKUP_OPTION, t, "the 'I'll pick it up' option")
        zip_box = _first_visible(page, ZIP_INPUT)
        if zip_box is not None and cfg.zip_code not in (zip_box.input_value() or ""):
            zip_box.fill(cfg.zip_code)
            zip_box.press("Enter")
            click_if_present(page, SHOW_STORES, "store search")

        step = f"select store {store.name}"
        store_rx = re.escape(store.name)
        click_any(
            page,
            [_role("radio", store_rx), _text(rf"^\s*(apple\s+)?{store_rx}\s*$"), _text(store_rx)],
            t,
            f"store '{store.name}'",
        )

        step = "pickup time"
        select = _first_visible(page, PICKUP_TIME_SELECT)
        if select is not None:
            values = select.locator("option").evaluate_all(
                "opts => opts.filter(o => o.value && !o.disabled).map(o => o.value)"
            )
            if values:
                select.select_option(values[0])
                log.info("checkout: picked earliest pickup window %s", values[0])

        step = "pickup details / payment"
        _advance_to_review(page, cfg, t)

        step = "review"
        place = wait_for_any(page, PLACE_ORDER, t, "Place Your Order button")
        if not cfg.checkout.place_order:
            notifier.send(
                "iPhone in your bag - PLACE ORDER NOW",
                f"Pickup at {store.name} is ready on the review page. Click 'Place Your Order'.",
                page.url,
            )
            return False

        step = "place order"
        place.click()
        wait_for_any(page, ORDER_DONE, 60, "order confirmation")
        notifier.send("ORDER PLACED", f"Pickup at {store.name}. Check your email for the confirmation.", page.url)
        return True

    except Exception as e:
        log.exception("checkout stopped at step %r", step)
        notifier.send(
            "Finish checkout by hand NOW",
            f"Auto-checkout stopped at '{step}' ({e}). The browser is open on that page.",
            page.url if page else cfg.product_url,
        )
        return False


def _advance_to_review(page, cfg, step_timeout, max_clicks=8):
    """Click through pickup contact / payment until "Place Your Order" shows.

    The Continue buttons share markup with the final Place Order button, so
    anything labelled "Place ... Order" is excluded here; only the explicit
    `place_order` setting may click it.
    """
    cvv = os.environ.get(cfg.checkout.cvv_env, "")
    clicks = 0
    deadline = time.monotonic() + step_timeout
    while True:
        if _first_visible(page, PLACE_ORDER) is not None:
            return
        cvv_box = _first_visible(page, CVV_INPUT)
        if cvv_box is not None and not cvv_box.input_value():
            if not cvv:
                raise StepFailed(f"card security code needed (set the {cfg.checkout.cvv_env} env var)")
            cvv_box.fill(cvv)
        btn = _first_visible(page, CONTINUE, exclude=PLACE_ORDER_RX)
        if btn is not None:
            if clicks >= max_clicks:
                raise StepFailed("clicked Continue repeatedly without reaching the review page")
            log.info("checkout: clicking %r", btn.inner_text(timeout=1000).strip())
            btn.click()
            clicks += 1
            page.wait_for_timeout(1500)
            deadline = time.monotonic() + step_timeout
            continue
        if time.monotonic() > deadline:
            raise StepFailed("could not find a Continue or Place Order button")
        page.wait_for_timeout(250)


def _handle_sign_in(page, cfg, notifier):
    page.wait_for_timeout(1500)
    if "signin" not in page.url.lower():
        return
    if cfg.checkout.guest and click_if_present(page, GUEST, "Continue as Guest", timeout=5):
        return
    notifier.send(
        "Sign in to Apple to continue checkout",
        "Checkout is waiting on the Apple sign-in page. Sign in in the open browser; the bot continues after.",
        page.url,
    )
    deadline = time.monotonic() + 5 * 60
    while "signin" in page.url.lower():
        if time.monotonic() > deadline:
            raise StepFailed("still on the sign-in page after 5 minutes")
        page.wait_for_timeout(500)
