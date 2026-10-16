"""Build Apple's pickup-availability query and parse its response.

This is the same JSON endpoint the product page itself calls to render the
"Pickup: ..." line, so polling it looks like a normal page refresh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode

FULFILLMENT_PATH = "/shop/fulfillment-messages"

PART_RE = re.compile(r"\b[A-Z0-9]{4,5}\d?[A-Z]{1,2}/A\b")


@dataclass(frozen=True)
class StoreStatus:
    number: str
    name: str
    city: str
    available: bool
    display: str
    quote: str

    def label(self) -> str:
        city = f" ({self.city})" if self.city else ""
        return f"{self.name}{city} [{self.number}]"


def build_url(base: str, part: str, zip_code: str, store: str | None = None) -> str:
    params = {
        "fae": "true",
        "pl": "true",
        "mts.0": "regular",
        "mts.1": "compact",
        "parts.0": part,
        "location": zip_code,
    }
    if store:
        params["store"] = store
        params["searchNearby"] = "true"
    return f"{base.rstrip('/')}{FULFILLMENT_PATH}?{urlencode(params)}"


def parse_stores(data: dict, part: str) -> list[StoreStatus]:
    """Return per-store pickup status for `part`. Tolerates missing keys."""
    content = (data.get("body") or {}).get("content") or {}
    stores = (content.get("pickupMessage") or {}).get("stores") or []
    result = []
    for store in stores:
        parts = store.get("partsAvailability") or {}
        info = parts.get(part)
        if info is None and len(parts) == 1:
            info = next(iter(parts.values()))
        info = info or {}
        display = str(info.get("pickupDisplay") or "unknown")
        quote = (
            info.get("pickupSearchQuote")
            or info.get("storePickupQuote")
            or ((info.get("messageTypes") or {}).get("regular") or {}).get("storePickupQuote")
            or ""
        )
        result.append(
            StoreStatus(
                number=str(store.get("storeNumber") or ""),
                name=str(store.get("storeName") or ""),
                city=str(store.get("city") or ""),
                available=display.lower() == "available",
                display=display,
                quote=_strip_tags(str(quote)),
            )
        )
    return result


def match_store(store: StoreStatus, wanted: str) -> bool:
    """`wanted` is a store number (e.g. "R123") or a case-insensitive name fragment."""
    wanted = wanted.strip().lower()
    if not wanted:
        return False
    return wanted == store.number.lower() or wanted in store.name.lower()


def pick_target(stores: list[StoreStatus], wanted: list[str]) -> StoreStatus | None:
    """First store, in the user's priority order, that has the part available."""
    for name in wanted:
        for store in stores:
            if store.available and match_store(store, name):
                return store
    return None


def find_part_numbers(text: str) -> list[str]:
    """Distinct Apple part numbers (e.g. MXYZ3LL/A) in order of appearance."""
    seen: dict[str, None] = {}
    for match in PART_RE.findall(text):
        seen.setdefault(match, None)
    return list(seen)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()
