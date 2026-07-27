from __future__ import annotations

from ..common.consts import (
    FIREWALL_RULE_DATA_ACTION,
    FIREWALL_RULE_DATA_DESCRIPTION,
    FIREWALL_RULE_DATA_DESTINATION,
    FIREWALL_RULE_DATA_IS_ENABLED,
    FIREWALL_RULE_DATA_IS_IPV6,
    FIREWALL_RULE_DATA_LOG,
    FIREWALL_RULE_DATA_NUMBER,
    FIREWALL_RULE_DATA_PROTOCOL,
    FIREWALL_RULE_DATA_RULESET,
    FIREWALL_RULE_DATA_RULESET_DEFAULT_ACTION,
    FIREWALL_RULE_DATA_RULESET_DESCRIPTION,
    FIREWALL_RULE_DATA_SOURCE,
    FIREWALL_RULE_DATA_STATE,
    FIREWALL_RULE_ID_IPV6_PREFIX,
    FIREWALL_RULE_ID_SEPARATOR,
)
from ..common.enums import FirewallRulesetTypes


class EdgeOSFirewallRuleData:
    """A single rule of an EdgeOS firewall rule-set."""

    ruleset: str
    ruleset_type: FirewallRulesetTypes
    ruleset_description: str | None
    ruleset_default_action: str | None
    number: str
    description: str | None
    action: str | None
    protocol: str | None
    log: str | None
    state: dict | None
    source: dict | None
    destination: dict | None
    is_enabled: bool

    def __init__(self, ruleset: str, ruleset_type: FirewallRulesetTypes, number: str):
        self.ruleset = ruleset
        self.ruleset_type = ruleset_type
        self.ruleset_description = None
        self.ruleset_default_action = None
        self.number = number

        self.description = None
        self.action = None
        self.protocol = None
        self.log = None
        self.state = None
        self.source = None
        self.destination = None

        self.is_enabled = True

    @property
    def unique_id(self) -> str:
        """Identify the rule across both address families.

        IPv4 and IPv6 rule-sets are stored in separate sections of the
        configuration and may therefore share a name.
        """
        parts = [self.ruleset, self.number]

        if self.is_ipv6:
            parts.insert(0, FIREWALL_RULE_ID_IPV6_PREFIX)

        return FIREWALL_RULE_ID_SEPARATOR.join(parts)

    @property
    def is_ipv6(self) -> bool:
        return self.ruleset_type == FirewallRulesetTypes.IPV6

    def to_dict(self):
        obj = {
            FIREWALL_RULE_DATA_RULESET: self.ruleset,
            FIREWALL_RULE_DATA_NUMBER: self.number,
            FIREWALL_RULE_DATA_IS_IPV6: self.is_ipv6,
            FIREWALL_RULE_DATA_DESCRIPTION: self.description,
            FIREWALL_RULE_DATA_ACTION: self.action,
            FIREWALL_RULE_DATA_PROTOCOL: self.protocol,
            FIREWALL_RULE_DATA_LOG: self.log,
            FIREWALL_RULE_DATA_STATE: self.state,
            FIREWALL_RULE_DATA_SOURCE: self.source,
            FIREWALL_RULE_DATA_DESTINATION: self.destination,
            FIREWALL_RULE_DATA_RULESET_DESCRIPTION: self.ruleset_description,
            FIREWALL_RULE_DATA_RULESET_DEFAULT_ACTION: self.ruleset_default_action,
            FIREWALL_RULE_DATA_IS_ENABLED: self.is_enabled,
        }

        return obj

    def get_attributes(self):
        rule_attributes = self.to_dict()

        attributes = {
            attribute: rule_attributes[attribute]
            for attribute in rule_attributes
            if attribute != FIREWALL_RULE_DATA_IS_ENABLED
            and rule_attributes[attribute] is not None
        }

        return attributes

    def __repr__(self):
        to_string = f"{self.to_dict()}"

        return to_string
