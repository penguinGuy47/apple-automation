"""Two ways to hit the availability endpoint.

* ``http``    - plain `requests` session. Lightweight, but Apple's CDN is more
                likely to answer a non-browser client with 403 after a while.
* ``browser`` - a real Chrome window (persistent profile, signed in to your
                Apple ID) that calls the endpoint with `fetch()` from the
                product page, exactly like the page does. Slightly heavier,
                but the same tab is warm and signed in when checkout starts.
"""

from __future__ import annotations

import json
import time

import requests


class Blocked(Exception):
    """Apple answered with a rate-limit / bot-wall response."""

    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"HTTP {status} {detail}".strip())
        self.status = status


BLOCK_STATUSES = {403, 429, 503, 541}


def _decode(status: int, text: str) -> dict:
    if status in BLOCK_STATUSES:
        raise Blocked(status)
    if status != 200:
        raise RuntimeError(f"unexpected HTTP {status}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # An HTML challenge page instead of JSON means we are being throttled.
        raise Blocked(status, "(non-JSON response)")


class HttpEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._warmed = False

    def _warm_up(self):
        # Load the product page once so we hold the same cookies a visitor would.
        self.session.get(self.cfg.product_url, timeout=20)
        self._warmed = True

    def fetch(self, url: str) -> dict:
        if not self._warmed:
            self._warm_up()
        r = self.session.get(
            url,
            timeout=15,
            headers={"Accept": "application/json", "Referer": self.cfg.product_url},
        )
        if r.status_code in BLOCK_STATUSES:
            self._warmed = False  # refresh cookies after backing off
        return _decode(r.status_code, r.text)

    def page(self):
        return None

    def close(self):
        self.session.close()


FETCH_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}});
  return {status: r.status, text: await r.text()};
}"""


class BrowserEngine:
    RELOAD_EVERY_SECONDS = 20 * 60

    def __init__(self, cfg):
        from .browser import open_context

        self.cfg = cfg
        self.pw, self.context = open_context(cfg.checkout, headless=cfg.checkout.headless)
        self._page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self._loaded_at: float | None = None

    def _ensure_loaded(self):
        if self._loaded_at is None or time.monotonic() - self._loaded_at > self.RELOAD_EVERY_SECONDS:
            self._page.goto(self.cfg.product_url, wait_until="domcontentloaded", timeout=45_000)
            self._loaded_at = time.monotonic()

    def fetch(self, url: str) -> dict:
        self._ensure_loaded()
        res = self._page.evaluate(FETCH_JS, url)
        if res["status"] in BLOCK_STATUSES:
            self._loaded_at = None  # reload the page after backing off
        return _decode(res["status"], res["text"])

    def page(self):
        return self._page

    def close(self):
        try:
            self.context.close()
        finally:
            self.pw.stop()


def make_engine(cfg):
    return BrowserEngine(cfg) if cfg.engine == "browser" else HttpEngine(cfg)
