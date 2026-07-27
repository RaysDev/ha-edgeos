"""Offline check of the firewall entity descriptions and the set/delete payload."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.consts import (  # noqa: E402
    API_URL_DATA,
    DATA_SYSTEM_FIREWALL,
    FIREWALL_DATA_RULE,
    SYSTEM_DATA_DISABLE,
    UPDATE_DATE_ENDPOINTS,
)
from custom_components.edgeos.common.entity_descriptions import (  # noqa: E402
    PLATFORMS,
    get_entity_descriptions,
)
from custom_components.edgeos.common.enums import (  # noqa: E402
    DeviceTypes,
    FirewallRulesetTypes,
)
from custom_components.edgeos.models.edge_os_firewall_rule_data import (  # noqa: E402
    EdgeOSFirewallRuleData,
)
from homeassistant.const import Platform  # noqa: E402

ok = True


def check(label, actual, expected):
    global ok
    passed = actual == expected
    ok &= passed
    print(
        f"[{'PASS' if passed else 'FAIL'}] {label}: {actual!r}"
        + ("" if passed else f" != {expected!r}")
    )


def keys(platform, is_monitored, is_admin):
    return sorted(
        d.key
        for d in get_entity_descriptions(
            platform, DeviceTypes.FIREWALL_RULE, is_monitored, is_admin
        )
    )


# An admin sees a controllable switch, a read-only user gets a binary sensor
check(
    "admin switches",
    keys(Platform.SWITCH, False, True),
    ["firewall_rule_status"],
)
check("admin binary sensors", keys(Platform.BINARY_SENSOR, False, True), [])
check(
    "non-admin switches",
    keys(Platform.SWITCH, False, False),
    [],
)
check(
    "non-admin binary sensors",
    keys(Platform.BINARY_SENSOR, False, False),
    ["firewall_rule_status"],
)

# Counters only appear once the rule is marked as monitored
check("unmonitored sensors", keys(Platform.SENSOR, False, True), [])
check(
    "monitored sensors",
    keys(Platform.SENSOR, True, True),
    [],
)

check(
    "firewall platforms registered",
    all(
        p in PLATFORMS
        for p in (Platform.SWITCH, Platform.BINARY_SENSOR, Platform.SENSOR)
    ),
    True,
)

# The counters were the only consumer, so the endpoint is no longer fetched -
# it is the most expensive call the integration made, running iptables on the
# router for every chain, once a minute
check("fw_stats no longer polled", "fw_stats" in UPDATE_DATE_ENDPOINTS, False)


# --- payload built by RestAPI.set_firewall_rule_state ----------------------
def payload(rule):
    return {
        DATA_SYSTEM_FIREWALL: {
            str(rule.ruleset_type): {
                rule.ruleset: {
                    FIREWALL_DATA_RULE: {rule.number: {SYSTEM_DATA_DISABLE: None}}
                }
            }
        }
    }


ipv4 = EdgeOSFirewallRuleData("WAN_IN", FirewallRulesetTypes.IPV4, "20")
ipv6 = EdgeOSFirewallRuleData("WAN_IN", FirewallRulesetTypes.IPV6, "20")

check(
    "ipv4 payload",
    json.dumps(payload(ipv4)),
    '{"firewall": {"name": {"WAN_IN": {"rule": {"20": {"disable": null}}}}}}',
)
check(
    "ipv6 payload",
    json.dumps(payload(ipv6)),
    '{"firewall": {"ipv6-name": {"WAN_IN": {"rule": {"20": {"disable": null}}}}}}',
)
check("ipv4 id", ipv4.unique_id, "WAN_IN:20")
check("ipv6 id", ipv6.unique_id, "IPv6:WAN_IN:20")

check(
    "disable endpoint",
    API_URL_DATA.format(base_url="https://router", action="set"),
    "https://router/api/edge/set.json",
)
check(
    "enable endpoint",
    API_URL_DATA.format(base_url="https://router", action="delete"),
    "https://router/api/edge/delete.json",
)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
