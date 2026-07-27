"""Check that a diagnostics report carries no credentials.

The payload embeds the API data as received, which includes the session cookies
and the entire `get.json` configuration tree. A diagnostics download is the file
users attach to bug reports, so what matters is that the key list the
integration hands to Home Assistant's redaction helper actually covers the
secrets EdgeOS puts in that tree.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.diagnostics import TO_REDACT  # noqa: E402
from homeassistant.components.diagnostics import (  # noqa: E402
    REDACTED,
    async_redact_data,
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


# Shaped after what `get_debug_data` produces, with the secret bearing parts of a
# real EdgeOS configuration tree.
DEBUG_DATA = {
    "config": {
        "username": "ubnt",
        "host": "192.168.1.1",
        "unit": "b",
        "monitored-devices": {"aa:bb:cc:dd:ee:ff": True},
    },
    "data": {
        "api": {
            "cookies": {
                "beaker.session.id": "6f1c5a0e",
                "X-CSRF-TOKEN": "9d2b",
            },
            "session-id": "6f1c5a0e",
            "product": "ER-X",
            "system": {
                "system": {
                    "host-name": "edgerouter",
                    "login": {
                        "user": {
                            "ubnt": {
                                "authentication": {
                                    "encrypted-password": "$6$rounds$abcdef",
                                    "plaintext-password": None,
                                    "public-keys": {"laptop": {"key": "AAAAB3Nza"}},
                                },
                                "level": "admin",
                            }
                        }
                    },
                },
                "interfaces": {
                    "wireguard": {"wg0": {"private-key": "4Hn0s=", "peer": {}}},
                    "ethernet": {"eth0": {"address": "dhcp"}},
                },
                "vpn": {
                    "ipsec": {
                        "site-to-site": {
                            "peer": {"203.0.113.9": {"pre-shared-secret": "hunter2"}}
                        }
                    }
                },
                "service": {
                    "dns": {
                        "dynamic": {
                            "interface": {
                                "eth0": {
                                    "service": {
                                        "dyndns": {
                                            "login": "someone",
                                            "password": "hunter2",
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "firewall": {"name": {"WAN_IN": {"rule": {"10": {"action": "drop"}}}}},
            },
        },
        "websockets": {"received-messages": 1234},
    },
    "processors": {"Firewall Rule": [{"ruleset": "WAN_IN", "number": "10"}]},
}

redacted = async_redact_data(DEBUG_DATA, TO_REDACT)

api = redacted["data"]["api"]
config_tree = api["system"]
login = config_tree["system"]["login"]["user"]["ubnt"]

check("session cookies redacted", api["cookies"], REDACTED)
check("session id redacted", api["session-id"], REDACTED)
check("password hash subtree redacted", login["authentication"], REDACTED)
check(
    "wireguard private key redacted",
    config_tree["interfaces"]["wireguard"]["wg0"]["private-key"],
    REDACTED,
)
check(
    "ipsec pre-shared secret redacted",
    config_tree["vpn"]["ipsec"]["site-to-site"]["peer"]["203.0.113.9"][
        "pre-shared-secret"
    ],
    REDACTED,
)
check(
    "dynamic dns password redacted",
    config_tree["service"]["dns"]["dynamic"]["interface"]["eth0"]["service"]["dyndns"][
        "password"
    ],
    REDACTED,
)

# What has to survive, or the report stops being useful
check("hostname kept", config_tree["system"]["host-name"], "edgerouter")
check("user level kept", login["level"], "admin")
check("username kept", redacted["config"]["username"], "ubnt")
check("router address kept", redacted["config"]["host"], "192.168.1.1")
check("product kept", api["product"], "ER-X")
check(
    "firewall rules kept",
    config_tree["firewall"]["name"]["WAN_IN"]["rule"]["10"]["action"],
    "drop",
)
check(
    "interface configuration kept",
    config_tree["interfaces"]["ethernet"]["eth0"],
    {"address": "dhcp"},
)
check(
    "processor output kept", redacted["processors"]["Firewall Rule"][0]["number"], "10"
)

# Redaction must not damage the live data the coordinator keeps using
check(
    "original cookies untouched",
    DEBUG_DATA["data"]["api"]["cookies"]["X-CSRF-TOKEN"],
    "9d2b",
)
check(
    "original password hash untouched",
    DEBUG_DATA["data"]["api"]["system"]["system"]["login"]["user"]["ubnt"][
        "authentication"
    ]["encrypted-password"],
    "$6$rounds$abcdef",
)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
