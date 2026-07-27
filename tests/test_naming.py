"""Check how a rule-set device and its rule entities are named and identified.

The device identifier and the device name used to be the same string - the
identifier was a slug of the name - so changing how a name reads would have
orphaned every device already registered. They are computed apart now, and the
assertions below are what keep them apart.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.entity_descriptions import (  # noqa: E402
    ENTITY_DESCRIPTIONS,
)
from custom_components.edgeos.common.enums import DeviceTypes, EntityKeys  # noqa: E402
from custom_components.edgeos.data_processors.firewall_processor import (  # noqa: E402
    FirewallProcessor,
)
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


def config(rules, ruleset="WAN_OUT", family="name"):
    return {
        "system": {"host-name": "EMDXV6H7XVOW44"},
        "firewall": {family: {ruleset: {"default-action": "drop", "rule": rules}}},
    }


RULES = {
    "10": {"action": "accept", "description": "Allow DNS out"},
    "80": {"action": "drop", "description": "block_guest_tv"},
    "760": {"action": "drop", "description": "block-kid-tablet"},
    "999": {"action": "drop"},
}

processor = FirewallProcessor(None)
processor.update({"system": config(RULES)}, {})


def device(rule_id):
    return processor.get_device_info(rule_id)


def identifier(rule_id):
    return list(device(rule_id)["identifiers"])[0][1]


# --- one device for the whole rule-set --------------------------------------
check(
    "every rule of a rule-set lands on one device",
    len({identifier(rule_id) for rule_id in processor.get_rules()}),
    1,
)
check(
    "the device is named after the rule-set",
    device("WAN_OUT:760")["name"],
    "EMDXV6H7XVOW44 Firewall WAN_OUT",
)
check(
    "its model marks it a rule-set",
    device("WAN_OUT:760")["model"],
    DeviceTypes.FIREWALL_RULESET,
)

# --- the identifier is not the name -----------------------------------------
# Pinned to the formula rather than to the current name, so that rewording the
# name in the future cannot silently orphan a device.
check(
    "the identifier is built from the model, not the display name",
    identifier("WAN_OUT:760"),
    slugify("EMDXV6H7XVOW44 Firewall Rule Set WAN_OUT"),
)
check(
    "which is not what the old per-rule device was identified by",
    identifier("WAN_OUT:760") == slugify("EMDXV6H7XVOW44 Firewall Rule WAN_OUT:760"),
    False,
)

# --- entity names ------------------------------------------------------------
check(
    "a dashed description reads as a name",
    processor.get_item_name("WAN_OUT:760"),
    "Block Kid Tablet",
)
check("an underscored one too", processor.get_item_name("WAN_OUT:80"), "Block Guest Tv")
check(
    "a description already written as prose is untouched",
    processor.get_item_name("WAN_OUT:10"),
    "Allow DNS out",
)
check(
    "a rule with no description falls back to its number",
    processor.get_item_name("WAN_OUT:999"),
    "rule 999",
)

for description, expected in [
    ("vpn-killswitch", "Vpn Killswitch"),
    ("WAN-OUT-BLOCK", "WAN OUT BLOCK"),
    ("IPv6_block", "IPv6 Block"),
    ("  spaced  out  ", "spaced  out"),
    ("block--double--dash", "Block Double Dash"),
    ("", None),
    ("   ", None),
    ("---", None),
    (None, None),
    # A word that already carries a capital is left alone, so a name the user
    # chose that way is not mangled
    ("iPhone-Gabi", "iPhone Gabi"),
    ("Android-Nexus6", "Android Nexus6"),
    ("desktop-pc", "Desktop Pc"),
    ("NAS_Main", "NAS Main"),
    ("eduroam-wifi", "Eduroam Wifi"),
]:
    check(
        f"prettify {description!r}", FirewallProcessor._prettify(description), expected
    )

# --- IPv4 and IPv6 rule-sets of the same name are different devices ----------
dual = FirewallProcessor(None)
dual.update(
    {
        "system": {
            "system": {"host-name": "EMDXV6H7XVOW44"},
            "firewall": {
                "name": {"WAN_OUT": {"rule": {"10": {"description": "v4-rule"}}}},
                "ipv6-name": {"WAN_OUT": {"rule": {"10": {"description": "v6-rule"}}}},
            },
        }
    },
    {},
)

check(
    "both address families are discovered",
    sorted(dual.get_rules()),
    ["IPv6:WAN_OUT:10", "WAN_OUT:10"],
)
check(
    "they do not share a device",
    list(dual.get_device_info("WAN_OUT:10")["identifiers"])[0][1]
    == list(dual.get_device_info("IPv6:WAN_OUT:10")["identifiers"])[0][1],
    False,
)
check(
    "the IPv6 device says so",
    dual.get_device_info("IPv6:WAN_OUT:10")["name"],
    "EMDXV6H7XVOW44 Firewall IPv6 WAN_OUT",
)

# --- a rule the processor no longer holds ------------------------------------
# `_remove_entities_of_device` can ask about one of these, so it must not raise
check(
    "a dropped rule still resolves to its rule-set device",
    list(processor.get_device_info("WAN_OUT:12345")["identifiers"])[0][1],
    identifier("WAN_OUT:760"),
)
check(
    "and names itself after the rule id",
    processor.get_item_name("WAN_OUT:12345"),
    "WAN_OUT:12345",
)

# --- the entity descriptions -------------------------------------------------
firewall = [
    d for d in ENTITY_DESCRIPTIONS if d.device_type == DeviceTypes.FIREWALL_RULE
]

check(
    "only the toggle and its read-only twin remain",
    sorted({d.key for d in firewall}),
    [EntityKeys.FIREWALL_RULE_STATUS],
)
check("there are exactly two of them", len(firewall), 2)
check(
    "both let Home Assistant compose the name",
    all(d.has_entity_name for d in firewall),
    True,
)

# The entity unique_id is what preserves entity ids and history across the
# restructure, so it must not have moved with the device
check(
    "a rule's entity unique_id is unchanged",
    slugify(
        "_".join(["edgeos", "switch", EntityKeys.FIREWALL_RULE_STATUS, "WAN_OUT:760"])
    ),
    "edgeos_switch_firewall_rule_status_wan_out_760",
)

print()
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
