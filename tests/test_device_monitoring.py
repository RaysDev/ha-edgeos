"""Check that a device only gets a device of its own once it is monitored.

Every EdgeOS device used to need a Home Assistant device purely to carry its
monitoring toggle, which on a network with fifty static mappings is fifty
devices showing one switch each. The toggles now sit together on one device, and
because Home Assistant creates a device only when an entity points at it, an
unmonitored device produces none at all.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    REMOVED_ITEM_GRACE_PERIOD,
)
from custom_components.edgeos.common.entity_descriptions import (  # noqa: E402
    PLATFORMS,
    get_entity_descriptions,
)
from custom_components.edgeos.common.enums import DeviceTypes, EntityKeys  # noqa: E402
from custom_components.edgeos.data_processors.device_processor import (  # noqa: E402
    DeviceProcessor,
)
from custom_components.edgeos.managers import (  # noqa: E402
    coordinator as coordinator_module,
)
from custom_components.edgeos.managers.coordinator import Coordinator  # noqa: E402
from homeassistant.const import Platform  # noqa: E402
from homeassistant.util import slugify  # noqa: E402

ok = True


def check(label, actual, expected):
    global ok
    passed = actual == expected
    ok &= passed
    print(
        f"[{'PASS' if passed else 'FAIL'}] {label}: {actual!r}"
        + ("" if passed else f" != {expected!r}")
    )


class FakeConfigData:
    username = "ubnt"


CONFIG = {
    "system": {"host-name": "EMDXV6H7XVOW44"},
    "service": {
        "dhcp-server": {
            "shared-network-name": {
                "LAN": {
                    "subnet": {
                        "192.168.0.0/24": {
                            "static-mapping": {
                                "Android-Nexus6": {
                                    "ip-address": "192.168.0.10",
                                    "mac-address": "aa:bb:cc:dd:ee:01",
                                },
                                "iPhone-Gabi": {
                                    "ip-address": "192.168.0.11",
                                    "mac-address": "aa:bb:cc:dd:ee:02",
                                },
                            }
                        }
                    }
                }
            }
        }
    },
}

processor = DeviceProcessor(FakeConfigData())
processor.update({"system": CONFIG}, {})

NEXUS = "aa:bb:cc:dd:ee:01"
IPHONE = "aa:bb:cc:dd:ee:02"


# --- the shared device -------------------------------------------------------
shared = processor.get_shared_device_info()

check(
    "it is named for what it does", shared["name"], "EMDXV6H7XVOW44 Device Monitoring"
)
check("its model marks it the shared one", shared["model"], DeviceTypes.DEVICE_LIST)
check(
    "its identifier comes from the model, not the display name",
    list(shared["identifiers"])[0][1],
    slugify("EMDXV6H7XVOW44 Device List"),
)
check(
    "which is not what a device of its own would be identified by",
    list(shared["identifiers"])[0][1]
    == list(processor.get_device_info(NEXUS)["identifiers"])[0][1],
    False,
)

# --- toggles are named after their device ------------------------------------
check("a hostname reads as a name", processor.get_item_name(NEXUS), "Android Nexus6")
check(
    "capitalisation the user chose survives",
    processor.get_item_name(IPHONE),
    "iPhone Gabi",
)
check(
    "a device the processor does not hold falls back to its id",
    processor.get_item_name("aa:bb:cc:dd:ee:99"),
    "aa:bb:cc:dd:ee:99",
)


# --- where each entity lands -------------------------------------------------
class FakeConfigManager:
    entry_id = "entry-1"

    @staticmethod
    def get_entity_name(entity_description, device_info):
        return f"{device_info.get('name')} {entity_description.key}"


class NamingCoordinator:
    get_device_info = Coordinator.get_device_info
    get_entity_name = Coordinator.get_entity_name

    def __init__(self):
        self._processors = {DeviceTypes.DEVICE: processor}
        self._config_manager = FakeConfigManager()


coordinator = NamingCoordinator()


def entities_for(item_id, is_monitored):
    """Where every entity of a device would be created, by device identifier."""
    placed = {}

    for platform in PLATFORMS:
        for description in get_entity_descriptions(
            platform, DeviceTypes.DEVICE, is_monitored, True
        ):
            device_info = coordinator.get_device_info(description, item_id)
            identifier = list(device_info["identifiers"])[0][1]

            placed.setdefault(identifier, []).append(description.key)

    return placed


unmonitored = entities_for(NEXUS, False)
shared_id = list(shared["identifiers"])[0][1]
own_id = list(processor.get_device_info(NEXUS)["identifiers"])[0][1]

check("an unmonitored device creates entities on one device only", len(unmonitored), 1)
check(
    "and that device is the shared one",
    sorted(unmonitored.get(shared_id, [])),
    [EntityKeys.DEVICE_MONITORED],
)
check(
    "so nothing points at a device of its own",
    own_id in unmonitored,
    False,
)

monitored = entities_for(NEXUS, True)

check("a monitored device uses both devices", len(monitored), 2)
check(
    "its toggle stays on the shared device",
    sorted(monitored.get(shared_id, [])),
    [EntityKeys.DEVICE_MONITORED],
)
check(
    "and everything else lands on its own",
    sorted(monitored.get(own_id, [])),
    sorted(
        [
            EntityKeys.DEVICE_RECEIVED_RATE,
            EntityKeys.DEVICE_SENT_RATE,
            EntityKeys.DEVICE_RECEIVED_TRAFFIC,
            EntityKeys.DEVICE_SENT_TRAFFIC,
            EntityKeys.DEVICE_TRACKER,
        ]
    ),
)

# --- naming, per entity kind -------------------------------------------------
toggle = next(
    description
    for description in get_entity_descriptions(
        Platform.SWITCH, DeviceTypes.DEVICE, False, True
    )
    if description.key == EntityKeys.DEVICE_MONITORED
)
sensor = next(
    description
    for description in get_entity_descriptions(
        Platform.SENSOR, DeviceTypes.DEVICE, True, True
    )
    if description.key == EntityKeys.DEVICE_RECEIVED_RATE
)

check(
    "the toggle is named after the device it refers to",
    coordinator.get_entity_name(toggle, shared, NEXUS),
    "Android Nexus6",
)
check(
    "a sensor is still named after its kind",
    coordinator.get_entity_name(sensor, processor.get_device_info(NEXUS), NEXUS),
    f"EMDXV6H7XVOW44 Device Android-Nexus6 {EntityKeys.DEVICE_RECEIVED_RATE}",
)

# The toggle's unique_id is what preserves entity ids and history across the
# move, so it must not have followed the device
check(
    "the toggle's unique_id is unchanged",
    slugify("_".join(["edgeos", "switch", EntityKeys.DEVICE_MONITORED, NEXUS])),
    "edgeos_switch_device_monitored_aa_bb_cc_dd_ee_01",
)


# --- removing a device once nothing points at it -----------------------------
class FakeDevice:
    def __init__(self, device_id, model=str(DeviceTypes.DEVICE)):
        self.id = device_id
        self.name = device_id
        self.model = model
        self.identifiers = {("EdgeOS", device_id)}


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


class FakeDeviceRegistry:
    def __init__(self, devices):
        self.devices = list(devices)
        self.removed = []

    def async_remove_device(self, device_id):
        self.removed.append(device_id)
        self.devices = [device for device in self.devices if device.id != device_id]


class Clock:
    current = 1_000_000.0

    @classmethod
    def monotonic(cls):
        return cls.current


class FakeAPI:
    def __init__(self, data):
        self.data = data


class SweepCoordinator:
    _async_remove_emptied_devices = Coordinator._async_remove_emptied_devices

    def __init__(self, api_data, devices, entities):
        self.hass = None
        self._api = FakeAPI(api_data)
        self._config_manager = FakeConfigManager()
        self._emptied_devices = {}
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


def build(api_data, devices, entities):
    instance = SweepCoordinator(api_data, devices, entities)
    FakeDr.registry = instance.device_registry
    FakeEr.registry = instance.entity_registry

    return instance


async def sweep_scenario():
    devices = [
        FakeDevice("dev-emptied"),
        FakeDevice("dev-monitored"),
        FakeDevice("dev-disabled"),
        FakeDevice("dev-ruleset", model=str(DeviceTypes.FIREWALL_RULESET)),
    ]
    entities = {
        "dev-monitored": [FakeEntity("sensor.rate"), FakeEntity("device_tracker.x")],
        # A disabled entity is still a registry entry, so its device is in use
        "dev-disabled": [FakeEntity("switch.disabled")],
    }

    instance = build({"system": CONFIG}, devices, entities)

    await instance._async_remove_emptied_devices()
    check(
        "nothing removed during the grace period", instance.device_registry.removed, []
    )
    check("the empty one is pending", list(instance._emptied_devices), ["dev-emptied"])

    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() - 5
    await instance._async_remove_emptied_devices()
    check(
        "still nothing just before the deadline", instance.device_registry.removed, []
    )

    Clock.current += 10
    await instance._async_remove_emptied_devices()
    check(
        "the emptied device is removed",
        instance.device_registry.removed,
        ["dev-emptied"],
    )
    check(
        "a device with entities, one with only disabled entities, and another "
        "type are all left alone",
        sorted(device.id for device in instance.device_registry.devices),
        ["dev-disabled", "dev-monitored", "dev-ruleset"],
    )
    check("pending cleared after removal", instance._emptied_devices, {})

    # a device that gains an entity before the deadline is not removed
    instance = build({"system": CONFIG}, [FakeDevice("dev-late")], {})
    await instance._async_remove_emptied_devices()
    check("marked pending", list(instance._emptied_devices), ["dev-late"])

    instance.entity_registry.entities._mapping["dev-late"] = [FakeEntity("switch.late")]
    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() + 10
    await instance._async_remove_emptied_devices()
    check("a device that filled up is spared", instance.device_registry.removed, [])
    check("and stops being a candidate", instance._emptied_devices, {})

    # nothing may be removed before a configuration has been read
    instance = build({}, [FakeDevice("dev-a"), FakeDevice("dev-b")], {})
    Clock.current += REMOVED_ITEM_GRACE_PERIOD.total_seconds() * 3
    await instance._async_remove_emptied_devices()
    await instance._async_remove_emptied_devices()
    check("no configuration means no removals", instance.device_registry.removed, [])


asyncio.run(sweep_scenario())

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
