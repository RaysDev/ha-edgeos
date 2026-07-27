"""Check the firmware update entity.

Home Assistant decides whether an update is available by comparing the installed
version against the latest one, so what matters is that those two only differ
when the router itself says there is something newer - and that a router which
has never checked is reported as unknown rather than as up to date.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    DOMAIN,
    RETIRED_ENTITIES,
)
from custom_components.edgeos.common.entity_descriptions import (  # noqa: E402
    ENTITY_DESCRIPTIONS,
)
from custom_components.edgeos.common.enums import EntityKeys  # noqa: E402
from custom_components.edgeos.data_processors.system_processor import (  # noqa: E402
    SystemProcessor,
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


class FakeConfigData:
    username = "ubnt"


INSTALLED = "EdgeRouter.ER-e300.v3.0.1.5862409.250924.1408"


def system(fw_latest):
    """A processor fed a `sys_info` payload with the given `fw-latest` block."""
    processor = SystemProcessor(FakeConfigData())

    sys_info = {"sw_ver": INSTALLED}

    if fw_latest is not None:
        sys_info["fw-latest"] = fw_latest

    processor.update(
        {
            "system": {
                "system": {
                    "host-name": "edgerouter",
                    "login": {"user": {"ubnt": {"level": "admin"}}},
                }
            },
            "sys_info": sys_info,
        },
        {"discover": {"fwversion": INSTALLED, "product": "ER-X"}, "system-stats": {}},
    )

    return processor


class FirmwareCoordinator:
    _get_firmware_data = Coordinator._get_firmware_data

    def __init__(self, processor):
        self._system_processor = processor


def firmware(fw_latest):
    return FirmwareCoordinator(system(fw_latest))._get_firmware_data(None)


# --- the model prefix is dropped so the version reads as the router shows it -
for raw, expected in [
    (INSTALLED, "v3.0.1.5862409.250924.1408"),
    ("EdgeRouter.ER-X.v2.0.9.1.5344937", "v2.0.9.1.5344937"),
    ("v3.0.1", "v3.0.1"),
    ("3.0.1", "3.0.1"),
    ("", None),
    (None, None),
]:
    check(f"version {raw!r}", SystemProcessor._get_version(raw), expected)


# --- the three states a router can be in ------------------------------------
available = firmware(
    {
        "state": "can-upgrade",
        "version": "EdgeRouter.ER-e300.v3.0.2.6000000.260101.1200",
        "url": "https://dl.ui.com/firmwares/edgemax/v3.0.2/ER-e300.tar",
    }
)

check(
    "an upgrade is offered as a newer version",
    available[ATTR_LATEST_VERSION],
    "v3.0.2.6000000.260101.1200",
)
check(
    "against the installed one",
    available[ATTR_INSTALLED_VERSION],
    "v3.0.1.5862409.250924.1408",
)
check(
    "with somewhere to read about it",
    available[ATTR_RELEASE_URL],
    "https://dl.ui.com/firmwares/edgemax/v3.0.2/ER-e300.tar",
)
check(
    "so Home Assistant sees an update",
    available[ATTR_INSTALLED_VERSION] != available[ATTR_LATEST_VERSION],
    True,
)

up_to_date = firmware({"state": "up-to-date"})

check(
    "a router with nothing newer reports the version it is on",
    up_to_date[ATTR_LATEST_VERSION],
    up_to_date[ATTR_INSTALLED_VERSION],
)
check(
    "so Home Assistant sees no update",
    up_to_date[ATTR_INSTALLED_VERSION] != up_to_date[ATTR_LATEST_VERSION],
    False,
)

never_checked = firmware(None)

check(
    "a router that never checked reports unknown, not up to date",
    never_checked[ATTR_LATEST_VERSION],
    None,
)
check(
    "while still saying what it is running",
    never_checked[ATTR_INSTALLED_VERSION],
    "v3.0.1.5862409.250924.1408",
)

# `can-upgrade` with no version is the router contradicting itself; unknown is
# more honest than either claiming an update or claiming there is none
contradictory = firmware({"state": "can-upgrade"})

check(
    "an upgrade with no version given stays unknown",
    contradictory[ATTR_LATEST_VERSION],
    None,
)


# --- it is an update entity, and it does not offer to install ---------------
firmware_descriptions = [
    description
    for description in ENTITY_DESCRIPTIONS
    if description.key == EntityKeys.FIRMWARE
]

check("there is exactly one", len(firmware_descriptions), 1)
check(
    "on the update platform",
    str(firmware_descriptions[0].platform),
    "update",
)

import custom_components.edgeos.update as update_platform  # noqa: E402

check(
    "installing is not offered",
    hasattr(update_platform.IntegrationUpdateEntity, "async_install"),
    False,
)


# --- the binary sensor it replaced is cleaned up ----------------------------
class FakeEntityRegistry:
    def __init__(self, known):
        self.known = dict(known)
        self.removed = []

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.known.get((domain, platform, unique_id))

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


class FakeEr:
    registry = None

    @staticmethod
    def async_get(hass):
        return FakeEr.registry


class RetiringCoordinator:
    _remove_retired_entities = Coordinator._remove_retired_entities

    def __init__(self, registry):
        self.hass = None
        FakeEr.registry = registry


from custom_components.edgeos.managers import (  # noqa: E402
    coordinator as coordinator_module,
)

coordinator_module.er = FakeEr

check(
    "the replaced binary sensor is on the list",
    ("binary_sensor", "edgeos_binary_sensor_firmware") in RETIRED_ENTITIES,
    True,
)

registry = FakeEntityRegistry(
    {
        ("binary_sensor", DOMAIN, "edgeos_binary_sensor_firmware"): (
            "binary_sensor.edgerouter_firmware"
        )
    }
)
RetiringCoordinator(registry)._remove_retired_entities()

check(
    "and is removed from the registry",
    registry.removed,
    ["binary_sensor.edgerouter_firmware"],
)

# an installation that never had it must not be disturbed
registry = FakeEntityRegistry({})
RetiringCoordinator(registry)._remove_retired_entities()

check("nothing to remove is not an error", registry.removed, [])

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
