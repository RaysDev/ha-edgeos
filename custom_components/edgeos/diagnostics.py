"""Diagnostics support for Tuya."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .common.consts import (
    DEVICE_DATA_MAC,
    DOMAIN,
    FIREWALL_RULE_DATA_IS_IPV6,
    FIREWALL_RULE_DATA_NUMBER,
    FIREWALL_RULE_DATA_RULESET,
    FIREWALL_RULE_ID_IPV6_PREFIX,
    FIREWALL_RULE_ID_SEPARATOR,
    INTERFACE_DATA_NAME,
)
from .common.enums import DeviceTypes
from .managers.coordinator import Coordinator

_LOGGER = logging.getLogger(__name__)

# The diagnostics payload embeds the API data as it was received, which includes
# the session cookies and the whole `get.json` configuration tree. Depending on
# how the router is set up, that tree carries user password hashes, VPN keys and
# dynamic DNS credentials - and a diagnostics download is the file users attach
# to bug reports. Matched at any depth.
#
# The username is deliberately not redacted: it is low value to an attacker, and
# the admin detection looks the logged in user up in the configuration by name,
# which is one of the things diagnostics are needed to debug.
TO_REDACT = {
    "authentication",
    "cookies",
    "encrypted-password",
    "key",
    "password",
    "plaintext-password",
    "pre-shared-key",
    "pre-shared-secret",
    "private-key",
    "secret",
    "session-id",
}


def _get_firewall_rule_ids(items: list[dict]) -> list[str]:
    """One rule per rule-set, since a rule-set is what a device now stands for."""
    rule_ids = {}

    for item in items:
        parts = [
            item.get(FIREWALL_RULE_DATA_RULESET),
            item.get(FIREWALL_RULE_DATA_NUMBER),
        ]

        if item.get(FIREWALL_RULE_DATA_IS_IPV6):
            parts.insert(0, FIREWALL_RULE_ID_IPV6_PREFIX)

        rule_id = FIREWALL_RULE_ID_SEPARATOR.join(parts)

        rule_ids.setdefault(FIREWALL_RULE_ID_SEPARATOR.join(parts[:-1]), rule_id)

    return list(rule_ids.values())


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.debug("Starting diagnostic tool")

    coordinator = hass.data[DOMAIN][entry.entry_id]

    return _async_get_diagnostics(hass, coordinator, entry)


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    return _async_get_diagnostics(hass, coordinator, entry, device)


@callback
def _async_get_diagnostics(
    hass: HomeAssistant,
    coordinator: Coordinator,
    entry: ConfigEntry,
    device: DeviceEntry | None = None,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.debug("Getting diagnostic information")

    # `async_redact_data` returns copies, so the coordinator's live data is not
    # touched by producing a diagnostics report
    debug_data = async_redact_data(coordinator.get_debug_data(), TO_REDACT)

    data = {
        "disabled_by": entry.disabled_by,
        "disabled_polling": entry.pref_disable_polling,
    }

    if device:
        data["config"] = debug_data["config"]
        data["data"] = debug_data["data"]
        data["processors"] = debug_data["processors"]

        device_data = coordinator.get_device_data(device.model, device.identifiers)

        data |= _async_device_as_dict(
            hass,
            device.identifiers,
            device_data,
        )

    else:
        _LOGGER.debug("Getting diagnostic information for all devices")

        data = {
            "config": debug_data["config"],
            "data": debug_data["data"],
            "processors": debug_data["processors"],
        }

        processor_data = debug_data["processors"]
        system_data = processor_data[DeviceTypes.SYSTEM]
        device_data = processor_data[DeviceTypes.DEVICE]
        interface_data = processor_data[DeviceTypes.INTERFACE]
        firewall_rule_data = processor_data[DeviceTypes.FIREWALL_RULE]

        data.update(
            devices=[
                _async_device_as_dict(
                    hass,
                    coordinator.get_device_identifiers(
                        DeviceTypes.DEVICE, item.get(DEVICE_DATA_MAC)
                    ),
                    item,
                )
                for item in device_data
            ],
            interfaces=[
                _async_device_as_dict(
                    hass,
                    coordinator.get_device_identifiers(
                        DeviceTypes.INTERFACE, item.get(INTERFACE_DATA_NAME)
                    ),
                    item,
                )
                for item in interface_data
            ],
            firewall_rule_sets=[
                _async_device_as_dict(
                    hass,
                    coordinator.get_device_identifiers(
                        DeviceTypes.FIREWALL_RULE, rule_id
                    ),
                    coordinator.get_device_data(
                        str(DeviceTypes.FIREWALL_RULESET),
                        coordinator.get_device_identifiers(
                            DeviceTypes.FIREWALL_RULE, rule_id
                        ),
                    ),
                )
                for rule_id in _get_firewall_rule_ids(firewall_rule_data)
            ],
            system=_async_device_as_dict(
                hass,
                coordinator.get_device_identifiers(DeviceTypes.SYSTEM),
                system_data,
            ),
        )

    return data


@callback
def _async_device_as_dict(
    hass: HomeAssistant, identifiers, additional_data: dict
) -> dict[str, Any]:
    """Represent an EdgeOS based device as a dictionary."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    ha_device = device_registry.async_get_device(identifiers=identifiers)
    data = {}

    if ha_device:
        data["device"] = {
            "name": ha_device.name,
            "name_by_user": ha_device.name_by_user,
            "disabled": ha_device.disabled,
            "disabled_by": ha_device.disabled_by,
            "data": additional_data,
            "entities": [],
        }

        ha_entities = er.async_entries_for_device(
            entity_registry,
            device_id=ha_device.id,
            include_disabled_entities=True,
        )

        for entity_entry in ha_entities:
            state = hass.states.get(entity_entry.entity_id)
            state_dict = None
            if state:
                state_dict = dict(state.as_dict())

                # The context doesn't provide useful information in this case.
                state_dict.pop("context", None)

            data["device"]["entities"].append(
                {
                    "disabled": entity_entry.disabled,
                    "disabled_by": entity_entry.disabled_by,
                    "entity_category": entity_entry.entity_category,
                    "device_class": entity_entry.device_class,
                    "original_device_class": entity_entry.original_device_class,
                    "icon": entity_entry.icon,
                    "original_icon": entity_entry.original_icon,
                    "unit_of_measurement": entity_entry.unit_of_measurement,
                    "state": state_dict,
                }
            )

    return data
