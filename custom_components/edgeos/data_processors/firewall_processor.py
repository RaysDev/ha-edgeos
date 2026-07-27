import logging
import sys
from time import monotonic

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import slugify

from ..common.consts import (
    API_DATA_SYSTEM,
    DATA_SYSTEM_FIREWALL,
    DEFAULT_NAME,
    FIREWALL_DATA_ACTION,
    FIREWALL_DATA_DEFAULT_ACTION,
    FIREWALL_DATA_DESCRIPTION,
    FIREWALL_DATA_DESTINATION,
    FIREWALL_DATA_LOG,
    FIREWALL_DATA_PROTOCOL,
    FIREWALL_DATA_RULE,
    FIREWALL_DATA_SOURCE,
    FIREWALL_DATA_STATE,
    FIREWALL_DEVICE_NAME,
    FIREWALL_RULE_ID_SEPARATOR,
    PENDING_STATE_TIMEOUT,
    SYSTEM_DATA_DISABLE,
)
from ..common.enums import DeviceTypes, FirewallRulesetTypes
from ..models.config_data import ConfigData
from ..models.edge_os_firewall_rule_data import EdgeOSFirewallRuleData
from .base_processor import BaseProcessor

_LOGGER = logging.getLogger(__name__)


class FirewallProcessor(BaseProcessor):
    """Discovers the firewall rules configured on the router.

    A rule-set is the device and each of its rules is one entity on it, so a
    router with eighty rules produces a handful of devices rather than eighty.
    """

    _rules: dict[str, EdgeOSFirewallRuleData]

    def __init__(self, config_data: ConfigData):
        super().__init__(config_data)

        self.processor_type = DeviceTypes.FIREWALL_RULE

        self._rules: dict[str, EdgeOSFirewallRuleData] = {}
        self._pending_states: dict[str, tuple[bool, float]] = {}

    def set_pending_state(self, unique_id: str, is_enabled: bool):
        """Record a state written to the router but not yet read back.

        The processor re-reads the cached configuration on every WebSocket
        message, so without this the switch would flip back to its previous
        position within a second of being toggled, until the configuration is
        fetched again.
        """
        self._pending_states[unique_id] = (is_enabled, monotonic())

        rule = self._rules.get(unique_id)

        if rule is not None:
            rule.is_enabled = is_enabled

    def _apply_pending_state(self, rule: EdgeOSFirewallRuleData):
        pending = self._pending_states.get(rule.unique_id)

        if pending is None:
            return

        is_enabled, requested_at = pending

        if is_enabled == rule.is_enabled:
            # The router now reports what was asked for
            self._pending_states.pop(rule.unique_id)

            return

        if monotonic() - requested_at > PENDING_STATE_TIMEOUT.total_seconds():
            # The change never took effect, stop hiding the real state
            _LOGGER.warning(
                f"Firewall rule {rule.unique_id} did not reach the requested "
                f"state within {PENDING_STATE_TIMEOUT}, reporting {rule.is_enabled}"
            )

            self._pending_states.pop(rule.unique_id)

            return

        rule.is_enabled = is_enabled

    def get_rules(self) -> list[str]:
        return list(self._rules.keys())

    def get_all(self) -> list[dict]:
        items = [self._rules[item_key].to_dict() for item_key in self._rules]

        return items

    def get_data(self, unique_id: str) -> EdgeOSFirewallRuleData:
        rule_data = self._rules.get(unique_id)

        return rule_data

    def get_firewall_rule(self, identifiers: set[tuple[str, str]]) -> dict | None:
        """Every rule of the rule-set the given device stands for."""
        device_identifier = list(identifiers)[0][1]

        rules = [
            self._rules[unique_id].to_dict()
            for unique_id in self._rules
            if self._get_ruleset_identifier(self._get_ruleset_id(unique_id))
            == device_identifier
        ]

        return None if not rules else {FIREWALL_DATA_RULE: rules}

    def get_device_info(self, item_id: str | None = None) -> DeviceInfo:
        """The device of the rule-set a rule belongs to.

        Deliberately not `BaseProcessor.get_device_info`, which derives the
        identifier by slugifying the display name. Keeping those two apart is
        what lets a rule-set be renamed, or the name be reworded here, without
        orphaning the device already registered in Home Assistant.
        """
        ruleset_id = self._get_ruleset_id(item_id)

        return DeviceInfo(
            identifiers={(DEFAULT_NAME, self._get_ruleset_identifier(ruleset_id))},
            name=self._get_ruleset_name(ruleset_id),
            model=DeviceTypes.FIREWALL_RULESET,
            manufacturer=DEFAULT_NAME,
            via_device=(DEFAULT_NAME, self._hostname),
        )

    def get_item_name(self, item_id: str | None = None) -> str | None:
        """What one rule is called within its rule-set device.

        Home Assistant joins this to the device name, so the entity reads
        `EDGEROUTER Firewall WAN_OUT Block Kid Tablet`.
        """
        rule = self._rules.get(item_id)

        if rule is None:
            return None if item_id is None else str(item_id)

        description = self._prettify(rule.description)

        return f"rule {rule.number}" if description is None else description

    @staticmethod
    def _get_ruleset_id(item_id: str | None) -> str | None:
        """The rule-set half of a rule id, `IPv6:WAN_OUT:760` -> `IPv6:WAN_OUT`."""
        if item_id is None:
            return None

        ruleset_id, separator, _number = item_id.rpartition(FIREWALL_RULE_ID_SEPARATOR)

        return ruleset_id if separator else item_id

    def _get_ruleset_identifier(self, ruleset_id: str | None) -> str:
        parts = [self._hostname, str(DeviceTypes.FIREWALL_RULESET), ruleset_id]

        return slugify(" ".join(part for part in parts if part is not None))

    def _get_ruleset_name(self, ruleset_id: str | None) -> str:
        # `IPv6:WAN_OUT` reads as `IPv6 WAN_OUT`
        ruleset = (
            None
            if ruleset_id is None
            else ruleset_id.replace(FIREWALL_RULE_ID_SEPARATOR, " ")
        )

        parts = [self._hostname, FIREWALL_DEVICE_NAME, ruleset]

        return " ".join(part for part in parts if part is not None)

    def _process_api_data(self):
        super()._process_api_data()

        try:
            system_section = self._api_data.get(API_DATA_SYSTEM, {})

            # No configuration has been read yet. Carrying on would find no rules
            # and conclude that every one of them was removed.
            if not isinstance(system_section, dict) or not system_section:
                return

            firewall_section = system_section.get(DATA_SYSTEM_FIREWALL, {})

            if not isinstance(firewall_section, dict):
                return

            discovered: set[str] = set()

            for ruleset_type in FirewallRulesetTypes:
                rulesets = firewall_section.get(str(ruleset_type))

                if not isinstance(rulesets, dict):
                    continue

                for ruleset_name in rulesets:
                    ruleset_data = rulesets.get(ruleset_name)

                    self._extract_ruleset(
                        ruleset_type, ruleset_name, ruleset_data, discovered
                    )

            # Stop reporting rules that were removed from the configuration
            for removed_rule in [
                unique_id for unique_id in self._rules if unique_id not in discovered
            ]:
                _LOGGER.info(f"Firewall rule {removed_rule} is no longer configured")

                self._rules.pop(removed_rule)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract Firewall data, Error: {ex}, Line: {line_number}"
            )

    def _extract_ruleset(
        self,
        ruleset_type: FirewallRulesetTypes,
        ruleset_name: str,
        ruleset_data: dict | None,
        discovered: set[str],
    ):
        if not isinstance(ruleset_data, dict):
            return

        rules = ruleset_data.get(FIREWALL_DATA_RULE)

        if not isinstance(rules, dict):
            return

        for rule_number in rules:
            rule = self._extract_rule(
                ruleset_type,
                ruleset_name,
                ruleset_data,
                str(rule_number),
                rules.get(rule_number),
            )

            if rule is not None:
                discovered.add(rule.unique_id)

    def _extract_rule(
        self,
        ruleset_type: FirewallRulesetTypes,
        ruleset_name: str,
        ruleset_data: dict,
        rule_number: str,
        rule_data: dict | None,
    ) -> EdgeOSFirewallRuleData | None:
        try:
            # A rule without any attribute is serialized as `null` by EdgeOS
            if rule_data is None:
                rule_data = {}

            if not isinstance(rule_data, dict):
                return None

            rule = EdgeOSFirewallRuleData(ruleset_name, ruleset_type, rule_number)

            rule.ruleset_description = ruleset_data.get(FIREWALL_DATA_DESCRIPTION)
            rule.ruleset_default_action = ruleset_data.get(FIREWALL_DATA_DEFAULT_ACTION)

            rule.description = rule_data.get(FIREWALL_DATA_DESCRIPTION)
            rule.action = rule_data.get(FIREWALL_DATA_ACTION)
            rule.protocol = rule_data.get(FIREWALL_DATA_PROTOCOL)
            rule.log = rule_data.get(FIREWALL_DATA_LOG)
            rule.state = rule_data.get(FIREWALL_DATA_STATE)
            rule.source = rule_data.get(FIREWALL_DATA_SOURCE)
            rule.destination = rule_data.get(FIREWALL_DATA_DESTINATION)

            # EdgeOS marks a rule as disabled by adding a valueless `disable` node,
            # its value is `null`, so only the presence of the key is meaningful
            rule.is_enabled = SYSTEM_DATA_DISABLE not in rule_data

            self._apply_pending_state(rule)

            self._rules[rule.unique_id] = rule

            return rule

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract firewall rule {ruleset_name}/{rule_number}, "
                f"Error: {ex}, "
                f"Line: {line_number}"
            )

            return None
