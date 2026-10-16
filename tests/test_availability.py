import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apple_pickup import availability

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "fulfillment_sample.json").read_text())
PART = "MTEST1LL/A"


def test_build_url():
    url = availability.build_url("https://www.apple.com/", PART, "60173")
    parsed = urlparse(url)
    assert parsed.path == "/shop/fulfillment-messages"
    q = parse_qs(parsed.query)
    assert q["parts.0"] == [PART]
    assert q["location"] == ["60173"]
    assert "store" not in q


def test_parse_stores():
    stores = availability.parse_stores(SAMPLE, PART)
    assert [s.name for s in stores] == ["Woodfield", "Old Orchard"]
    assert not stores[0].available
    assert stores[1].available
    assert stores[1].quote == "AvailableToday"


def test_pick_target_respects_list_and_priority():
    stores = availability.parse_stores(SAMPLE, PART)
    assert availability.pick_target(stores, ["Woodfield"]) is None
    assert availability.pick_target(stores, ["woodfield", "old orch"]).number == "R200"
    assert availability.pick_target(stores, ["R200"]).name == "Old Orchard"


def test_woodfield_available():
    data = copy.deepcopy(SAMPLE)
    data["body"]["content"]["pickupMessage"]["stores"][0]["partsAvailability"][PART]["pickupDisplay"] = "available"
    stores = availability.parse_stores(data, PART)
    assert availability.pick_target(stores, ["Woodfield", "Old Orchard"]).name == "Woodfield"


def test_parse_tolerates_garbage():
    assert availability.parse_stores({}, PART) == []
    assert availability.parse_stores({"body": {"content": {"pickupMessage": None}}}, PART) == []


def test_find_part_numbers():
    text = 'parts.0=MXYZ3LL/A&x "partNumber":"MXYZ3LL/A","other":"MAB12LL/A"'
    assert availability.find_part_numbers(text) == ["MXYZ3LL/A", "MAB12LL/A"]


def test_decode_flags_throttling():
    import pytest

    from apple_pickup.engines import Blocked, _decode

    assert _decode(200, '{"ok": 1}') == {"ok": 1}
    with pytest.raises(Blocked):
        _decode(403, "")
    with pytest.raises(Blocked):
        _decode(200, "<html>Access Denied</html>")
