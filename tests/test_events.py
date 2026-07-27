"""Check the event driven configuration path.

Covers the `config-change` subscription, the signal it raises, and the pending
state that stops a toggled switch from bouncing back before the router has been
re-read.
"""
import copy as _copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    PENDING_STATE_TIMEOUT,
    SIGNAL_CONFIG_CHANGED,
    WS_CONFIG_CHANGE_KEY,
)
from custom_components.edgeos.data_processors import (  # noqa: E402
    firewall_processor as fw_module,
)
from custom_components.edgeos.data_processors.firewall_processor import (  # noqa: E402
    FirewallProcessor,
)
from custom_components.edgeos.managers.websockets import WebSockets  # noqa: E402

ok = True


def check(label, actual, expected):
    global ok
    passed = actual == expected
    ok &= passed
    print(
        f"[{'PASS' if passed else 'FAIL'}] {label}: {actual!r}"
        + ("" if passed else f" != {expected!r}")
    )


# --- the router announces commits, and we subscribe to that -----------------
ws = WebSockets(None, None, None)
topics = list(ws._get_ws_handlers().keys())

check("config-change is subscribed to", WS_CONFIG_CHANGE_KEY in topics, True)
check(
    "existing subscriptions kept",
    sorted(topics),
    ["config-change", "discover", "export", "interfaces", "system-stats"],
)

subscription = ws._get_subscription_data()
check(
    "config-change present in subscription payload",
    '{"name":"config-change"}' in subscription,
    True,
)


# --- only a finished commit triggers a refresh ------------------------------
class FakeWS:
    def __init__(self):
        self.sent = []

    def _async_dispatcher_send(self, signal, *args):
        self.sent.append(signal)


fake = FakeWS()
WebSockets._handle_config_change(fake, {"commit": "started"})
check("commit started does not refresh", fake.sent, [])

WebSockets._handle_config_change(fake, {"commit": "ended"})
check("commit ended raises the signal", fake.sent, [SIGNAL_CONFIG_CHANGED])

fake.sent = []
WebSockets._handle_config_change(fake, None)
WebSockets._handle_config_change(fake, "")
WebSockets._handle_config_change(fake, {})
check("malformed payloads ignored", fake.sent, [])


# --- pending state survives the stale configuration -------------------------
CONFIG = {
    "system": {"host-name": "edgerouter"},
    "firewall": {
        "name": {
            "WAN_IN": {
                "default-action": "drop",
                "rule": {
                    "10": {"action": "accept"},
                    "20": {"action": "drop", "disable": None},
                },
            }
        }
    },
}


class FakeClock:
    """Virtual monotonic clock, so the pending-state timeout costs no wall time."""

    current = 1_000_000.0

    @classmethod
    def monotonic(cls):
        return cls.current


fw_module.monotonic = FakeClock.monotonic

processor = FirewallProcessor(None)
processor.update({"system": CONFIG}, {})

check("rule 10 starts enabled", processor.get_data("WAN_IN:10").is_enabled, True)
check("rule 20 starts disabled", processor.get_data("WAN_IN:20").is_enabled, False)

# Home Assistant disables rule 10, the router has not been re-read yet
processor.set_pending_state("WAN_IN:10", False)
check(
    "switch reflects the write immediately",
    processor.get_data("WAN_IN:10").is_enabled,
    False,
)

# Every websocket message re-runs the processor against the stale configuration,
# this is what used to make the switch snap back
for _ in range(5):
    processor.update({"system": CONFIG}, {})

check(
    "stale config does not undo the write",
    processor.get_data("WAN_IN:10").is_enabled,
    False,
)
check("other rules unaffected", processor.get_data("WAN_IN:20").is_enabled, False)

# The configuration is re-read and now agrees
CONFIRMED = _copy.deepcopy(CONFIG)
CONFIRMED["firewall"]["name"]["WAN_IN"]["rule"]["10"]["disable"] = None
processor.update({"system": CONFIRMED}, {})

check("confirmed state holds", processor.get_data("WAN_IN:10").is_enabled, False)
check("pending cleared once confirmed", processor._pending_states, {})

# A write the router silently ignored must not be hidden forever
processor.set_pending_state("WAN_IN:20", True)
processor.update({"system": CONFIG}, {})
check(
    "pending held before the timeout", processor.get_data("WAN_IN:20").is_enabled, True
)

FakeClock.current += PENDING_STATE_TIMEOUT.total_seconds() + 1
processor.update({"system": CONFIG}, {})
check(
    "pending expires and the truth returns",
    processor.get_data("WAN_IN:20").is_enabled,
    False,
)
check("expired pending cleared", processor._pending_states, {})

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
