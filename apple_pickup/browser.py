from __future__ import annotations

from pathlib import Path


def open_context(checkout_cfg, headless: bool = False):
    """Persistent Chrome profile so your Apple ID sign-in survives restarts."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    profile = Path(checkout_cfg.profile_dir).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(headless=headless, viewport={"width": 1280, "height": 900})
    try:
        if checkout_cfg.browser_channel:
            ctx = pw.chromium.launch_persistent_context(
                str(profile), channel=checkout_cfg.browser_channel, **kwargs
            )
        else:
            ctx = pw.chromium.launch_persistent_context(str(profile), **kwargs)
    except Exception:
        if not checkout_cfg.browser_channel:
            pw.stop()
            raise
        # Chrome not installed: fall back to Playwright's bundled Chromium.
        ctx = pw.chromium.launch_persistent_context(str(profile), **kwargs)
    return pw, ctx
