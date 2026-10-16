from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class NotifyConfig:
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    discord_webhook: str = ""
    desktop: bool = True
    sound: bool = True
    open_browser: bool = True


@dataclass
class CheckoutConfig:
    enabled: bool = False
    place_order: bool = False
    guest: bool = False
    headless: bool = False
    browser_channel: str = "chrome"
    profile_dir: str = ".browser-profile"
    cvv_env: str = "APPLE_CVV"
    step_timeout_seconds: float = 20


@dataclass
class Config:
    product_url: str
    part_number: str = ""
    zip_code: str = "60173"
    stores: list[str] = field(default_factory=lambda: ["Woodfield"])
    interval_seconds: float = 12
    jitter: float = 0.3
    engine: str = "browser"
    start_at: str = ""
    max_backoff_seconds: float = 900
    apple_base: str = "https://www.apple.com"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    )
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    checkout: CheckoutConfig = field(default_factory=CheckoutConfig)

    def start_time(self) -> datetime | None:
        return datetime.fromisoformat(self.start_at) if self.start_at else None


def load(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    notify = NotifyConfig(**raw.pop("notify", {}))
    checkout = CheckoutConfig(**raw.pop("checkout", {}))
    cfg = Config(**raw, notify=notify, checkout=checkout)
    if cfg.engine not in ("browser", "http"):
        raise ValueError(f"engine must be 'browser' or 'http', got {cfg.engine!r}")
    if cfg.interval_seconds < 5:
        raise ValueError("interval_seconds below 5 is asking to get rate-limited; use 8-20")
    if not cfg.stores:
        raise ValueError("stores must list at least one store name or number")
    return cfg
