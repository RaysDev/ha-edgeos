"""Firewall rule lifecycle: adding, removing, renumbering, renaming a rule-set."""
import asyncio
import copy as _copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    DEFAULT_NAME,
    REMOVED_ITEM_GRACE_PERIOD,
)
from custom_components.edgeos.common.enums import DeviceTypes  # noqa: E402
from custom_components.edgeos.data_processors.firewall_processor import (  # noqa: E402
    FirewallProcessor,
)
from custom_components.edgeos.managers import (  # noqa: E402
    coordinator as coordinator_module,
)
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


def config(rules, ruleset="WAN_IN"):
    return {
        "system": {"host-name": "edgerouter"},
        "firewall": {"name": {ruleset: {"default-action": "drop", "rule": rules}}},
    }


BASE = config(
    {
        "10": {"action": "accept", "description": "Allow established"},
        "20": {"action": "drop", "description": "Block guest"},
    }
)


# --- processor level --------------------------------------------------------
processor = FirewallProcessor(None)
processor.update({"system": BASE}, {})
check("initial rules", sorted(processor.get_rules()), ["WAN_IN:10", "WAN_IN:20"])

# adding
added = _copy.deepcopy(BASE)
added["firewall"]["name"]["WAN_IN"]["rule"]["30"] = {"action": "drop"}
processor.update({"system": added}, {})
check(
    "added rule appears",
    sorted(processor.get_rules()),
    ["WAN_IN:10", "WAN_IN:20", "WAN_IN:30"],
)

# removing
processor.update({"system": BASE}, {})
check("removed rule pruned", sorted(processor.get_rules()), ["WAN_IN:10", "WAN_IN:20"])

# renumbering 20 -> 25 is a removal plus an addition
renumbered = config(
    {
        "10": {"action": "accept", "description": "Allow established"},
        "25": {"action": "drop", "description": "Block guest"},
    }
)
processor.update({"system": renumbered}, {})
check(
    "renumbered rule replaces the old one",
    sorted(processor.get_rules()),
    ["WAN_IN:10", "WAN_IN:25"],
)

# renaming the rule-set moves every rule under a new identity
renamed = config(
    {
        "10": {"action": "accept", "description": "Allow established"},
        "25": {"action": "drop", "description": "Block guest"},
    },
    ruleset="WAN_INBOUND",
)
processor.update({"system": renamed}, {})
check(
    "rule-set rename replaces every rule",
    sorted(processor.get_rules()),
    ["WAN_INBOUND:10", "WAN_INBOUND:25"],
)

# changing only the description keeps the identity, it is not a new rule
described = _copy.deepcopy(renamed)
described["firewall"]["name"]["WAN_INBOUND"]["rule"]["10"]["description"] = "Renamed"
processor.update({"system": described}, {})
check(
    "description change keeps identity",
    sorted(processor.get_rules()),
    ["WAN_INBOUND:10", "WAN_INBOUND:25"],
)
check(
    "description change is reflected",
    processor.get_data("WAN_INBOUND:10").description,
    "Renamed",
)

# a configuration that was never loaded must not look like a mass removal
processor.update({}, {})
check(
    "empty api data does not prune",
    sorted(processor.get_rules()),
    ["WAN_INBOUND:10", "WAN_INBOUND:25"],
)
processor.update({"system": {}}, {})
check(
    "empty system section does not prune",
    sorted(processor.get_rules()),
    ["WAN_INBOUND:10", "WAN_INBOUND:25"],
)

# a router with the firewall section removed entirely does prune
processor.update({"system": {"system": {"host-name": "edgerouter"}}}, {})
check("no firewall section prunes", processor.get_rules(), [])


# --- discovery bookkeeping --------------------------------------------------
class FakeCoordinatorKeys:
    _forget_removed_firewall_rules = Coordinator._forget_removed_firewall_rules

    def __init__(self, discovered):
        self._discovered_objects = set(discovered)


fake = FakeCoordinatorKeys(
    [
        "System",
        "Interface eth0",
        "Device aa:bb:cc:dd:ee:ff",
        "Firewall Rule WAN_IN:10",
        "Firewall Rule WAN_IN:20",
    ]
)
fake._forget_removed_firewall_rules(["WAN_IN:10"])
check(
    "removed rule forgotten, others untouched",
    sorted(fake._discovered_objects),
    sorted(
        [
            "System",
            "Interface eth0",
            "Device aa:bb:cc:dd:ee:ff",
            "Firewall Rule WAN_IN:10",
        ]
    ),
)


# --- device removal, with the grace period ----------------------------------
class FakeDevice:
    def __init__(self, device_id, identifier, model=str(DeviceTypes.FIREWALL_RULE)):
        self.id = device_id
        self.name = device_id
        self.model = model
        self.identifiers = {(DEFAULT_NAME, identifier)}


class FakeEntity:
    def __init__(self, entity_id):
        self.entity_id = entity_id


class FakeEntities:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_entries_for_device_id(self, device_id):
        return list(self._mapping.get(device_id, []))


class FakeEntityRegistry:
    def __init__(self, mapping):
        self.entities = FakeEntities(mapping)
        self.removed = []

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


class FakeDeviceRegistry:
    def __init__(self, devices):
        self.devices = list(devices)
        self.removed = []
        self.renamed = 0

    def async_remove_device(self, device_id):
        self.removed.append(device_id)
        self.devices = [d for d in self.devices if d.id != device_id]

    def async_update_device(self, device_id, name=None):
        self.renamed += 1

        for device in self.devices:
            if device.id == device_id and name is not None:
                device.name = name


class Clock:
    """Virtual monotonic clock, so the removal grace period costs no wall time."""

    current = 1_000_000.0

    @classmethod
    def monotonic(cls):
        return cls.current


class FakeConfigManager:
    entry_id = "entry-1"


class FakeAPI:
    def __init__(self, data):
        self.data = data


class SyncCoordinator:
    _async_sync_firewall_rule_devices = Coordinator._async_sync_firewall_rule_devices
    _sync_device_name = Coordinator._sync_device_name
    # Re-wrapped, otherwise it would be bound as an instance method here
    _get_device_identifier = staticmethod(Coordinator._get_device_identifier)

    def __init__(self, processor, api_data, devices, entities):
        self.hass = None
        self._api = FakeAPI(api_data)
        self._firewall_processor = processor
        self._config_manager = FakeConfigManager()
        self._missing_items = {}
        self.device_registry = FakeDeviceRegistry(devices)
        self.entity_registry = FakeEntityRegistry(entities)


class FakeDr:
    registry = None

    @staticmethod
    def async_get(hass):
        return FakeDr.registry

    @staticmethod
    def async_entries_for_config_entry(registry, entry_id):
        return list(registry.devices)


class FakeEr:
    registry = None

    @staticmethod
    def async_get(hass):
        return FakeEr.registry


coordinator_module.dr = FakeDr
coordinator_module.er = FakeEr
coordinator_module.monotonic = Clock.monotonic


def build(processor, api_data, devices, entities=None):
    coordinator = SyncCoordinator(processor, api_data, devices, entities or {})
    FakeDr.registry = coordinator.device_registry
    FakeEr.registry = coordinator.entity_registry

    return coordinator


def ruleset_device(processor, rule_id, device_id):
    identifier = list(processor.get_device_info(rule_id)["identifiers"])[0][1]
    device = FakeDevice(device_id, identifier, model=str(DeviceTypes.FIREWALL_RULESET))
    device.name = processor.get_device_info(rule_id)["name"]

    return device


TWO_RULESETS = {
    "system": {"host-name": "edgerouter"},
    "firewall": {
        "name": {
            "WAN_IN": {"default-action": "drop", "rule": {"10": {"action": "accept"}}},
            "WAN_OUT": {"default-action": "accept", "rule": {"20": {"action": "drop"}}},
        }
    },
}

ONE_RULESET = {
    "system": {"host-name": "edgerouter"},
    "firewall": {
        "name": {
            "WAN_IN": {"default-action": "drop", "rule": {"10": {"action": "accept"}}},
        }
    },
}


async def removal_scenario():
    # --- a whole rule-set is deleted on the router --------------------------
    live = FirewallProcessor(None)
    live.update({"system": TWO_RULESETS}, {})

    keep = ruleset_device(live, "WAN_IN:10", "dev-wan-in")
    gone = ruleset_device(live, "WAN_OUT:20", "dev-wan-out")
    other = FakeDevice("dev-other", "edgerouter_interface_eth0", model="Interface")

    entities = {"dev-wan-out": [FakeEntity("switch.gone"), FakeEntity("switch.gone2")]}
    coord = build(live, {"system": TWO_RULESETS}, [keep, gone, other], entities)

    live.update({"system": ONE_RULESET}, {})

    await coord._async_sync_firewall_rule_devices()
    check("nothing removed during the grace period", coord.device_registry.removed, [])
    check("removal is pending", len(coord._missing_items), 1)

    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() - 5
    await coord._async_sync_firewall_rule_devices()
    check(
        "still nothing removed just before the deadline",
        coord.device_registry.removed,
        [],
    )

    Clock.current += 10
    await coord._async_sync_firewall_rule_devices()
    check(
        "the rule-set device is removed after the grace period",
        coord.device_registry.removed,
        ["dev-wan-out"],
    )
    check(
        "its entities go with it",
        sorted(coord.entity_registry.removed),
        ["switch.gone", "switch.gone2"],
    )
    check(
        "the surviving rule-set and other devices are untouched",
        [d.id for d in coord.device_registry.devices],
        ["dev-wan-in", "dev-other"],
    )
    check("pending cleared after removal", coord._missing_items, {})

    # --- one rule of a rule-set is deleted ----------------------------------
    # The device belongs to the rule-set, so it must survive. Only the entity of
    # that rule goes, which the entity registry handles on its own.
    live = FirewallProcessor(None)
    live.update({"system": TWO_RULESETS}, {})

    both = {
        "system": {"host-name": "edgerouter"},
        "firewall": {
            "name": {
                "WAN_IN": {
                    "default-action": "drop",
                    "rule": {"10": {"action": "accept"}, "40": {"action": "drop"}},
                },
                "WAN_OUT": {
                    "default-action": "accept",
                    "rule": {"20": {"action": "drop"}},
                },
            }
        },
    }
    live.update({"system": both}, {})

    coord = build(
        live,
        {"system": both},
        [
            ruleset_device(live, "WAN_IN:10", "dev-wan-in"),
            ruleset_device(live, "WAN_OUT:20", "dev-wan-out"),
        ],
    )

    live.update({"system": TWO_RULESETS}, {})
    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() * 2
    await coord._async_sync_firewall_rule_devices()
    await coord._async_sync_firewall_rule_devices()

    check(
        "deleting one rule does not remove its rule-set device",
        coord.device_registry.removed,
        [],
    )

    # --- devices left by the version that gave every rule its own device ----
    live = FirewallProcessor(None)
    live.update({"system": ONE_RULESET}, {})

    legacy = FakeDevice(
        "dev-legacy",
        "edgerouter_firewall_rule_wan_in_10",
        model=str(DeviceTypes.FIREWALL_RULE),
    )
    coord = build(
        live,
        {"system": ONE_RULESET},
        [ruleset_device(live, "WAN_IN:10", "dev-wan-in"), legacy],
        {"dev-legacy": [FakeEntity("switch.old_monitored")]},
    )

    await coord._async_sync_firewall_rule_devices()
    check(
        "the legacy device waits out the grace period too",
        coord.device_registry.removed,
        [],
    )

    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() + 10
    await coord._async_sync_firewall_rule_devices()
    check(
        "the legacy per-rule device is retired",
        coord.device_registry.removed,
        ["dev-legacy"],
    )
    check(
        "and its orphaned entities with it",
        coord.entity_registry.removed,
        ["switch.old_monitored"],
    )
    check(
        "the rule-set device is kept",
        [d.id for d in coord.device_registry.devices],
        ["dev-wan-in"],
    )

    # --- a rule-set device whose name drifted -------------------------------
    live = FirewallProcessor(None)
    live.update({"system": ONE_RULESET}, {})

    stale = ruleset_device(live, "WAN_IN:10", "dev-wan-in")
    stale.name = "EDGEROUTER Firewall Rule WAN_IN:10"

    coord = build(live, {"system": ONE_RULESET}, [stale])
    await coord._async_sync_firewall_rule_devices()

    check("the device is renamed", stale.name, "EDGEROUTER Firewall WAN_IN")
    check("and not removed", coord.device_registry.removed, [])

    await coord._async_sync_firewall_rule_devices()
    check("renaming is not repeated", coord.device_registry.renamed, 1)

    # --- without a configuration read nothing may be removed ----------------
    live = FirewallProcessor(None)
    coord = build(live, {}, [FakeDevice("dev-a", "a"), FakeDevice("dev-b", "b")])

    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() * 3
    await coord._async_sync_firewall_rule_devices()
    await coord._async_sync_firewall_rule_devices()
    check("no configuration means no removals", coord.device_registry.removed, [])


asyncio.run(removal_scenario())

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
