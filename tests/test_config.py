"""Check the stored settings, and the guards around acting on a removed item.

An update interval of zero becomes the coordinator's `update_interval`, and
`timedelta(0)` reschedules with no delay - a tight loop that can only be undone
by editing the stored configuration by hand, so the value is clamped where it is
read as well as in the entity that sets it.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    ATTR_ACTIONS,
    DEFAULT_UPDATE_API_INTERVAL,
    DEFAULT_UPDATE_ENTITIES_INTERVAL,
    MINIMUM_UPDATE_INTERVAL,
    STORAGE_DATA_UPDATE_API_INTERVAL,
    STORAGE_DATA_UPDATE_ENTITIES_INTERVAL,
)
from custom_components.edgeos.common.entity_descriptions import (  # noqa: E402
    ENTITY_DESCRIPTIONS,
)
from custom_components.edgeos.common.enums import EntityKeys  # noqa: E402
from custom_components.edgeos.managers.config_manager import ConfigManager  # noqa: E402
from custom_components.edgeos.managers.coordinator import Coordinator  # noqa: E402

ok = True


def check(label, actual, expected):
    global ok
    passed = actual == expected
    ok &= passed
    print(
        f"[{'PASS' if passed else 'FAIL'}] {label}: {actual!r}"
        + ("" if passed else f" != {expected!r}")
    )


def manager(data):
    instance = ConfigManager(None)
    instance._data = data

    return instance


# --- intervals as read from the store ---------------------------------------
check(
    "the default entities interval is kept",
    manager({}).update_entities_interval,
    DEFAULT_UPDATE_ENTITIES_INTERVAL.total_seconds(),
)
check(
    "the default API interval is kept",
    manager({}).update_api_interval,
    DEFAULT_UPDATE_API_INTERVAL.total_seconds(),
)
check(
    "a stored zero is clamped",
    manager({STORAGE_DATA_UPDATE_ENTITIES_INTERVAL: 0}).update_entities_interval,
    float(MINIMUM_UPDATE_INTERVAL),
)
check(
    "a stored zero API interval is clamped",
    manager({STORAGE_DATA_UPDATE_API_INTERVAL: 0}).update_api_interval,
    float(MINIMUM_UPDATE_INTERVAL),
)
check(
    "a negative value is clamped",
    manager({STORAGE_DATA_UPDATE_ENTITIES_INTERVAL: -30}).update_entities_interval,
    float(MINIMUM_UPDATE_INTERVAL),
)
check(
    "a value that is not a number falls back to the default",
    manager({STORAGE_DATA_UPDATE_ENTITIES_INTERVAL: "fast"}).update_entities_interval,
    DEFAULT_UPDATE_ENTITIES_INTERVAL.total_seconds(),
)
check(
    "a boolean is not treated as a number",
    manager({STORAGE_DATA_UPDATE_API_INTERVAL: True}).update_api_interval,
    DEFAULT_UPDATE_API_INTERVAL.total_seconds(),
)
check(
    "a sensible value is left alone",
    manager({STORAGE_DATA_UPDATE_API_INTERVAL: 300}).update_api_interval,
    300.0,
)

# --- and as offered by the entity that sets them -----------------------------
minimums = {
    description.key: description.native_min_value
    for description in ENTITY_DESCRIPTIONS
    if description.key
    in (
        EntityKeys.UPDATE_ENTITIES_INTERVAL,
        EntityKeys.UPDATE_API_INTERVAL,
        EntityKeys.CONSIDER_AWAY_INTERVAL,
    )
}

check(
    "the entities interval cannot be set to zero",
    minimums[EntityKeys.UPDATE_ENTITIES_INTERVAL],
    MINIMUM_UPDATE_INTERVAL,
)
check(
    "the API interval cannot be set to zero",
    minimums[EntityKeys.UPDATE_API_INTERVAL],
    MINIMUM_UPDATE_INTERVAL,
)
# Zero is meaningful here: every device is considered away immediately
check(
    "the consider away interval may still be zero",
    minimums[EntityKeys.CONSIDER_AWAY_INTERVAL],
    0,
)


# --- saving must not raise on a store written by an older version ------------
class FakeStore:
    """Enough of a store for `_save` to run against."""

    def __init__(self, contents):
        self.contents = contents
        self.saved = None

    async def async_load(self):
        return self.contents

    async def async_save(self, data):
        self.saved = data


def saving_manager(data, stored):
    instance = ConfigManager(None)
    instance._data = data
    instance._entry_id = "entry-1"
    instance._store = FakeStore(stored)

    return instance


# The credentials are stripped from the store on every save. A store written by
# an older version simply has no such key, which used to raise `KeyError`.
saving = saving_manager(
    {"username": "ubnt", "password": "secret", "unit": "b"},
    {"entry-1": {"unit": "kb"}},
)

try:
    asyncio.run(saving._save())
    raised = None

except Exception as ex:
    raised = f"{type(ex).__name__}: {ex}"

check("saving with the credentials absent from the store does not raise", raised, None)
check(
    "the setting was written",
    saving._store.saved["entry-1"]["unit"],
    "b",
)
check(
    "the credentials were not written",
    [key for key in saving._store.saved["entry-1"] if key in ("username", "password")],
    [],
)

# And the case that always worked: credentials present in the store are removed
saving = saving_manager(
    {"username": "ubnt", "unit": "b"},
    {"entry-1": {"unit": "b", "username": "ubnt"}},
)
asyncio.run(saving._save())

check(
    "a credential already in the store is stripped",
    "username" in saving._store.saved["entry-1"],
    False,
)


# --- acting on an item the router no longer has ------------------------------
class Description:
    key = "firewall_rule_status"


class RemovedItemCoordinator:
    get_device_action = Coordinator.get_device_action

    def __init__(self, data):
        self._data = data

    def get_data(self, entity_description, item_id=None):
        return self._data


check(
    "no action for an item that reports nothing",
    RemovedItemCoordinator(None).get_device_action(
        Description(), "WAN_IN:20", "turn_on"
    ),
    None,
)
check(
    "no action when the data carries none",
    RemovedItemCoordinator({}).get_device_action(Description(), "WAN_IN:20", "turn_on"),
    None,
)
check(
    "no action for a key that is not offered",
    RemovedItemCoordinator({ATTR_ACTIONS: {"turn_off": print}}).get_device_action(
        Description(), "WAN_IN:20", "turn_on"
    ),
    None,
)
check(
    "the action is returned when it exists",
    RemovedItemCoordinator({ATTR_ACTIONS: {"turn_on": print}}).get_device_action(
        Description(), "WAN_IN:20", "turn_on"
    ),
    print,
)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
