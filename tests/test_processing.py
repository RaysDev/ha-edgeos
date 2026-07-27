"""Check the split between deriving the configuration and deriving statistics.

Statistics messages arrive once or twice a second and carry no configuration, so
they no longer re-derive it. What has to stay true is that they still update the
statistics, still discover interfaces that only ever appear in the stream, and
still fall back to a full pass before the configuration has been derived once.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.connectivity_status import (  # noqa: E402
    ConnectivityStatus,
)
from custom_components.edgeos.common.enums import DeviceTypes  # noqa: E402
from custom_components.edgeos.data_processors.device_processor import (  # noqa: E402
    DeviceProcessor,
)
from custom_components.edgeos.data_processors.firewall_processor import (  # noqa: E402
    FirewallProcessor,
)
from custom_components.edgeos.data_processors.interface_processor import (  # noqa: E402
    InterfaceProcessor,
)
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


API_DATA = {
    "system": {
        "system": {
            "host-name": "edgerouter",
            "login": {"user": {"ubnt": {"level": "admin"}}},
        },
        "interfaces": {"ethernet": {"eth0": {"description": "WAN"}}},
        "firewall": {
            "name": {
                "WAN_IN": {
                    "default-action": "drop",
                    "rule": {"10": {"action": "accept"}},
                }
            }
        },
    },
}


def interface_stats(name, rx_bytes, tx_bytes, mac=""):
    """The flattened shape `_handle_interfaces` leaves in the websocket data."""
    return {
        name: {
            "up": "true",
            "l1up": "true",
            "mac": mac,
            "multicast": 0,
            "addresses": [],
            "rx_bps": 100,
            "rx_bytes": rx_bytes,
            "rx_errors": 0,
            "rx_packets": 10,
            "rx_dropped": 0,
            "tx_bps": 200,
            "tx_bytes": tx_bytes,
            "tx_errors": 0,
            "tx_packets": 20,
            "tx_dropped": 0,
        }
    }


WS_DATA = {
    "system-stats": {"cpu": "7", "mem": "42", "uptime": "1000"},
    "discover": {"fwversion": "v3.0.1", "product": "ER-X"},
    "interfaces": interface_stats("eth0", 1000, 2000, "aa:bb:cc:dd:ee:ff"),
    "export": {},
}


class CountingFirewallProcessor(FirewallProcessor):
    """Counts how often the configuration is walked."""

    api_passes = 0

    def _process_api_data(self):
        CountingFirewallProcessor.api_passes += 1

        super()._process_api_data()


class FakeConfigData:
    # SystemProcessor looks the logged in user up in the configuration by name
    username = "ubnt"


class FakeConfigManager:
    entry_id = "entry-1"


class FakeConnection:
    status = ConnectivityStatus.Connected


class FakeApi:
    status = ConnectivityStatus.Connected

    def __init__(self, data):
        self.data = data


class FakeWebSockets:
    status = ConnectivityStatus.Connected

    def __init__(self, data):
        self.data = data


class FakeCoordinator:
    """Duck typed `self`, so the real coordinator methods run unmodified."""

    _on_data_changed = Coordinator._on_data_changed
    _on_ws_data_changed = Coordinator._on_ws_data_changed
    _discover = Coordinator._discover
    _forget_removed_firewall_rules = Coordinator._forget_removed_firewall_rules
    is_connected = Coordinator.is_connected

    def __init__(self, api_data, ws_data):
        self._api = FakeApi(api_data)
        self._websockets = FakeWebSockets(ws_data)
        self._config_manager = FakeConfigManager()
        self._api_data_processed = False
        self._discovered_objects = set()
        self.announced = []

        self._system_processor = SystemProcessor(FakeConfigData())
        self._device_processor = DeviceProcessor(FakeConfigData())
        self._interface_processor = InterfaceProcessor(FakeConfigData())
        self._firewall_processor = CountingFirewallProcessor(FakeConfigData())

        self._processors = {
            DeviceTypes.SYSTEM: self._system_processor,
            DeviceTypes.DEVICE: self._device_processor,
            DeviceTypes.INTERFACE: self._interface_processor,
            DeviceTypes.FIREWALL_RULE: self._firewall_processor,
        }

    # Discovery announcements are recorded rather than dispatched
    def _on_system_discovered(self):
        self._announce(str(DeviceTypes.SYSTEM))

    def _on_device_discovered(self, device_mac):
        self._announce(f"{DeviceTypes.DEVICE} {device_mac}")

    def _on_interface_discovered(self, interface_name):
        self._announce(f"{DeviceTypes.INTERFACE} {interface_name}")

    def _on_firewall_rule_discovered(self, rule_id):
        self._announce(f"{DeviceTypes.FIREWALL_RULE} {rule_id}")

    def _announce(self, key):
        if key not in self._discovered_objects:
            self._discovered_objects.add(key)
            self.announced.append(key)


async def main():
    # --- a statistics message before any configuration was derived ----------
    CountingFirewallProcessor.api_passes = 0
    coordinator = FakeCoordinator(API_DATA, WS_DATA)

    await coordinator._on_ws_data_changed("entry-1")

    check(
        "first statistics message falls back to a full pass",
        CountingFirewallProcessor.api_passes,
        1,
    )
    check("the configuration was derived", coordinator._api_data_processed, True)
    check(
        "the firewall rule was discovered",
        "Firewall Rule WAN_IN:10" in coordinator._discovered_objects,
        True,
    )
    check(
        "the interface was discovered",
        "Interface eth0" in coordinator._discovered_objects,
        True,
    )

    # --- further statistics messages leave the configuration alone ----------
    for _ in range(20):
        await coordinator._on_ws_data_changed("entry-1")

    check(
        "twenty more messages derive no configuration",
        CountingFirewallProcessor.api_passes,
        1,
    )

    # --- but they do keep the statistics current ----------------------------
    moved = {
        **WS_DATA,
        "system-stats": {"cpu": "63", "mem": "51", "uptime": "2000"},
        "interfaces": interface_stats("eth0", 5000, 6000, "aa:bb:cc:dd:ee:ff"),
    }
    coordinator._websockets.data = moved
    await coordinator._on_ws_data_changed("entry-1")

    check("system statistics still update", coordinator._system_processor.get().cpu, 63)
    check(
        "interface statistics still update",
        coordinator._interface_processor.get_data("eth0").received.total,
        5000,
    )
    check("still no configuration pass", CountingFirewallProcessor.api_passes, 1)

    # The configuration derived earlier is still there, not wiped by a pass that
    # only looked at statistics
    check(
        "the interface keeps its configured description",
        coordinator._interface_processor.get_data("eth0").description,
        "WAN",
    )
    check(
        "the firewall rule survives a statistics pass",
        coordinator._firewall_processor.get_rules(),
        ["WAN_IN:10"],
    )

    # --- an interface that exists only in the stream is still discovered -----
    coordinator._websockets.data = {
        **moved,
        "interfaces": {
            **moved["interfaces"],
            **interface_stats("pppoe0", 1, 1),
        },
    }
    await coordinator._on_ws_data_changed("entry-1")

    check(
        "a dynamic interface is discovered from the stream",
        "Interface pppoe0" in coordinator._discovered_objects,
        True,
    )

    # --- an API pass derives the configuration again -------------------------
    await coordinator._on_data_changed("entry-1")

    check(
        "an API pass derives the configuration", CountingFirewallProcessor.api_passes, 2
    )

    # --- a rule added on the router appears on the next API pass -------------
    added = {
        "system": {
            **API_DATA["system"],
            "firewall": {
                "name": {
                    "WAN_IN": {
                        "default-action": "drop",
                        "rule": {"10": {"action": "accept"}, "20": {"action": "drop"}},
                    }
                }
            },
        }
    }
    coordinator._api.data = added
    await coordinator._on_data_changed("entry-1")

    check(
        "a new rule is discovered on an API pass",
        "Firewall Rule WAN_IN:20" in coordinator._discovered_objects,
        True,
    )

    # --- nothing is derived while disconnected -------------------------------
    passes = CountingFirewallProcessor.api_passes
    coordinator._websockets.status = ConnectivityStatus.NotConnected

    await coordinator._on_ws_data_changed("entry-1")
    await coordinator._on_data_changed("entry-1")

    check(
        "a disconnected router derives nothing",
        CountingFirewallProcessor.api_passes,
        passes,
    )

    # --- another entry's signal is ignored ------------------------------------
    coordinator._websockets.status = ConnectivityStatus.Connected

    await coordinator._on_ws_data_changed("someone-else")
    await coordinator._on_data_changed("someone-else")

    check(
        "another config entry's signal is ignored",
        CountingFirewallProcessor.api_passes,
        passes,
    )

    print()
    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
