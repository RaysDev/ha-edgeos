"""Offline check of the firewall discovery/parsing logic.

Stubs out the Home Assistant and third party modules that the integration
imports at module level, so the data processor can be exercised against
realistic `/api/edge/get.json` payloads.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.data_processors.firewall_processor import (  # noqa: E402
    FirewallProcessor,
)

# --- realistic payloads ----------------------------------------------------
# Shaped after a real `/api/edge/get.json` GET section. Valueless configuration
# nodes (`disable`, `enable-default-log`) are serialised by EdgeOS as `null`.
GET_SECTION = {
    "system": {
        "host-name": "edgerouter",
        "login": {"user": {"ubnt": {"level": "admin"}}},
    },
    "firewall": {
        "all-ping": "enable",
        "name": {
            "WAN_IN": {
                "default-action": "drop",
                "description": "WAN to internal",
                "enable-default-log": None,
                "rule": {
                    "10": {
                        "action": "accept",
                        "description": "Allow established/related",
                        "protocol": "all",
                        "state": {"established": "enable", "related": "enable"},
                    },
                    "20": {
                        "action": "drop",
                        "description": "Drop invalid state",
                        "disable": None,
                        "log": "enable",
                        "state": {"invalid": "enable"},
                    },
                    "30": None,
                },
            },
            "WAN_LOCAL": {
                "default-action": "drop",
                "rule": {
                    "10": {
                        "action": "accept",
                        "description": "Allow established/related",
                        "state": {"established": "enable"},
                    }
                },
            },
            "LAN_IN": {"default-action": "accept"},
        },
        "ipv6-name": {
            "WAN_IN": {
                "default-action": "drop",
                "rule": {
                    "10": {"action": "accept", "description": "v6 established"},
                    "20": {"action": "drop", "disable": None},
                },
            }
        },
        "options": None,
    },
}

API_DATA = {"system": GET_SECTION}


def check(label, actual, expected):
    status = "PASS" if actual == expected else "FAIL"
    print(
        f"[{status}] {label}: {actual!r}"
        + ("" if status == "PASS" else f" != {expected!r}")
    )
    return status == "PASS"


processor = FirewallProcessor(None)
processor.update(API_DATA, {})

rules = sorted(processor.get_rules())
ok = True

ok &= check(
    "discovered rule ids",
    rules,
    [
        "IPv6:WAN_IN:10",
        "IPv6:WAN_IN:20",
        "WAN_IN:10",
        "WAN_IN:20",
        "WAN_IN:30",
        "WAN_LOCAL:10",
    ],
)

ok &= check("ipv4 rule 10 enabled", processor.get_data("WAN_IN:10").is_enabled, True)
ok &= check("ipv4 rule 20 disabled", processor.get_data("WAN_IN:20").is_enabled, False)
ok &= check("null rule 30 enabled", processor.get_data("WAN_IN:30").is_enabled, True)
ok &= check(
    "ipv6 rule 20 disabled", processor.get_data("IPv6:WAN_IN:20").is_enabled, False
)
ok &= check("ipv6 flag", processor.get_data("IPv6:WAN_IN:10").is_ipv6, True)
ok &= check("ipv4 not flagged ipv6", processor.get_data("WAN_IN:10").is_ipv6, False)

ok &= check(
    "rule attributes",
    processor.get_data("WAN_IN:20").get_attributes(),
    {
        "ruleset": "WAN_IN",
        "number": "20",
        "ipv6": False,
        "description": "Drop invalid state",
        "action": "drop",
        "log": "enable",
        "state": {"invalid": "enable"},
        "ruleset_description": "WAN to internal",
        "ruleset_default_action": "drop",
    },
)

# re-running the processor, which happens on every poll, must not duplicate or
# drop anything
processor.update(API_DATA, {})
ok &= check("stable across refresh", sorted(processor.get_rules()), rules)

# a device with no firewall configured at all must not explode
empty = FirewallProcessor(None)
empty.update({"system": {"system": {"host-name": "edgerouter"}}}, {})
ok &= check("no firewall section", empty.get_rules(), [])

# a rule deleted on the router must stop being reported
import copy as _copy  # noqa: E402

pruned_config = _copy.deepcopy(GET_SECTION)
del pruned_config["firewall"]["name"]["WAN_IN"]["rule"]["20"]
processor.update({"system": pruned_config}, {})
ok &= check("deleted rule pruned", "WAN_IN:20" in processor.get_rules(), False)
ok &= check("sibling rule kept", "WAN_IN:10" in processor.get_rules(), True)
ok &= check("lookup of deleted rule", processor.get_data("WAN_IN:20"), None)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
