"""Check how a device's address and lease state are kept up to date.

A device is matched to the traffic analysis stream by address. That address used
to be frozen at whatever it was when the device was first seen, so a device that
moved stopped being matched at all - traffic sensors froze and the tracker
reported away for good. What must not change is the hostname, because the device
identifier in Home Assistant is built from it.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.data_processors.device_processor import (  # noqa: E402
    DeviceProcessor,
)

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


def config(static_mappings=None, shared_networks=True):
    """A `get.json` system section with the DHCP server configured."""
    mappings = static_mappings or {}

    if not shared_networks:
        return {"system": {"host-name": "edgerouter"}, "service": {"dhcp-server": {}}}

    return {
        "system": {"host-name": "edgerouter"},
        "service": {
            "dhcp-server": {
                "shared-network-name": {
                    "LAN": {
                        "subnet": {
                            "192.168.1.0/24": {
                                "domain-name": "local",
                                "static-mapping": mappings,
                            }
                        }
                    }
                }
            }
        },
    }


def leases(entries):
    """A `dhcp-leases` payload: address -> lease."""
    return {"dhcp-server-leases": {"192.168.1.0/24": entries}}


STATIC = {"desktop": {"ip-address": "192.168.1.10", "mac-address": "aa:bb:cc:dd:ee:01"}}


# --- a static mapping whose address is changed on the router ----------------
processor = DeviceProcessor(FakeConfigData())
processor.update({"system": config(STATIC)}, {})

device = processor.get_data("aa:bb:cc:dd:ee:01")
check("device discovered", device.ip, "192.168.1.10")
check(
    "mapped by address",
    processor._devices_ip_mapping.get("192.168.1.10"),
    "aa:bb:cc:dd:ee:01",
)

moved = {"desktop": {"ip-address": "192.168.1.99", "mac-address": "aa:bb:cc:dd:ee:01"}}
processor.update({"system": config(moved)}, {})

check("address follows the configuration", device.ip, "192.168.1.99")
check(
    "new address is mapped",
    processor._devices_ip_mapping.get("192.168.1.99"),
    "aa:bb:cc:dd:ee:01",
)
check(
    "stale address is dropped", "192.168.1.10" in processor._devices_ip_mapping, False
)
check("still the same device", len(processor.get_devices()), 1)
check("hostname is not touched", device.hostname, "desktop")


# --- a device seen in the lease list before its static mapping is read ------
# Its identity has to end up not leased, or it is never offered as a tracker.
processor = DeviceProcessor(FakeConfigData())
processor.update(
    {
        "system": config({}),
        "dhcp-leases": leases(
            {
                "192.168.1.50": {
                    "mac": "aa:bb:cc:dd:ee:02",
                    "client-hostname": "laptop",
                }
            }
        ),
    },
    {},
)

check(
    "a lease is recorded as leased",
    processor.get_data("aa:bb:cc:dd:ee:02").is_leased,
    True,
)

processor.update(
    {
        "system": config(
            {
                "laptop": {
                    "ip-address": "192.168.1.50",
                    "mac-address": "aa:bb:cc:dd:ee:02",
                }
            }
        ),
        "dhcp-leases": leases(
            {
                "192.168.1.50": {
                    "mac": "aa:bb:cc:dd:ee:02",
                    "client-hostname": "laptop",
                }
            }
        ),
    },
    {},
)

check(
    "a static mapping clears the leased flag",
    processor.get_data("aa:bb:cc:dd:ee:02").is_leased,
    False,
)
check(
    "and it stays clear while the lease is still listed",
    processor.get_data("aa:bb:cc:dd:ee:02").is_leased,
    False,
)


# --- leased devices are counted once per pass, and without a shared network -
processor = DeviceProcessor(FakeConfigData())
processor.update(
    {
        "system": config(STATIC),
        "dhcp-leases": leases(
            {
                "192.168.1.60": {
                    "mac": "aa:bb:cc:dd:ee:03",
                    "client-hostname": "phone",
                },
                "192.168.1.61": {"mac": "aa:bb:cc:dd:ee:04", "client-hostname": "?"},
            }
        ),
    },
    {},
)

check("leased devices are listed", len(processor.get_leased_devices()), 2)
check(
    "a device with no hostname is listed by address",
    processor.get_leased_devices().get("192.168.1.61"),
    "aa:bb:cc:dd:ee:04",
)

# A router with no `shared-network-name` used to skip the leased pass entirely,
# so `Unknown Devices` always reported zero
processor = DeviceProcessor(FakeConfigData())
processor.update(
    {
        "system": config(shared_networks=False),
        "dhcp-leases": leases(
            {"192.168.1.60": {"mac": "aa:bb:cc:dd:ee:03", "client-hostname": "phone"}}
        ),
    },
    {},
)

check(
    "leases are counted with no shared network configured",
    len(processor.get_leased_devices()),
    1,
)


# --- a lease that moves ------------------------------------------------------
processor = DeviceProcessor(FakeConfigData())
first = leases(
    {"192.168.1.70": {"mac": "aa:bb:cc:dd:ee:05", "client-hostname": "tablet"}}
)
processor.update({"system": config(STATIC), "dhcp-leases": first}, {})

second = leases(
    {"192.168.1.71": {"mac": "aa:bb:cc:dd:ee:05", "client-hostname": "tablet"}}
)
processor.update({"system": config(STATIC), "dhcp-leases": second}, {})

check(
    "a renewed lease at a new address is followed",
    processor.get_data("aa:bb:cc:dd:ee:05").ip,
    "192.168.1.71",
)
check(
    "the leased list follows too",
    sorted(processor.get_leased_devices()),
    ["192.168.1.71"],
)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
