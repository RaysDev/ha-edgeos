import logging
import sys
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_registry import async_get as async_get_registry
from homeassistant.util import slugify

from ..managers.coordinator import Coordinator
from .consts import ADD_COMPONENT_SIGNALS, DOMAIN, DEFAULT_NAME
from .entity_descriptions import IntegrationEntityDescription, get_entity_descriptions
from .enums import DeviceTypes

_LOGGER = logging.getLogger(__name__)


async def async_setup_base_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: Platform,
    entity_type: type,
    async_add_entities,
):
    #####################################################################
    # This method gets called by HA for each platform we registered for, 
    # whenever we signal a new device is found
    # currently that happens in cordinator.py at _on_device_discovered.
    #####################################################################
    @callback
    def _async_handle_device(
        entry_id: str, device_type: DeviceTypes, item_id: str | None = None
    ):
        if entry.entry_id != entry_id:
            return

        try:
            coordinator = hass.data[DOMAIN][entry.entry_id]

            is_admin = coordinator.system.is_admin
            is_monitored = coordinator.config_manager.is_monitored(device_type, item_id)

            entity_descriptions = get_entity_descriptions(
                platform, device_type, is_monitored, is_admin
            )

            entities = [
                entity_type(hass, entity_description, coordinator, device_type, item_id)
                for entity_description in entity_descriptions
            ]


            #
            # while the traffic sensor entities are recreated each time we toggle the monitoring switch,
            # the switch itself does not go away. So no need to keep recreating it.
            #
            if platform == Platform.SWITCH and device_type == DeviceTypes.DEVICE:
                # track created unique_ids per ha config entry so we only skip duplicates in this runtime
                created_key = f"created_unique_ids_{entry.entry_id}"
                created_unique_ids = hass.data.setdefault(DOMAIN, {}).setdefault(
                    created_key, set()
                )

                # register cleanup so we don't leak the set after unload
                entry.async_on_unload(
                    lambda: hass.data.get(DOMAIN, {}).pop(created_key, None)
                )

                entity_description = entity_descriptions[0]
                unique_id = _build_unique_id(entity_description, item_id)

                # skip registring/creating new entities with HA if we already created this unique_id during this run
                if unique_id not in created_unique_ids:
                    async_add_entities(entities, True)
                    created_unique_ids.add(unique_id)
                else:
                    _LOGGER.debug(
                        "Skipping duplicate created-this-run entity unique_id=%s",
                        unique_id,
                    )

            else:
                async_add_entities(entities, True)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to initialize {platform}, Error: {ex}, Line: {line_number}"
            )

    for add_component_signal in ADD_COMPONENT_SIGNALS:
        entry.async_on_unload(
            async_dispatcher_connect(hass, add_component_signal, _async_handle_device)
        )


# Reusable function for building unique id. 
def _build_unique_id(entity_description, item_id):
    unique_id_parts = [
        DOMAIN,
        entity_description.platform,
        entity_description.key,
        item_id,
    ]
    unique_id_parts_clean = [str(p) for p in unique_id_parts if p is not None]
    return slugify("_".join(unique_id_parts_clean))


class IntegrationBaseEntity(CoordinatorEntity):
    _entity_description: IntegrationEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        entity_description: IntegrationEntityDescription,
        coordinator: Coordinator,
        device_type: DeviceTypes,
        item_id: str | None,
    ):
        super().__init__(coordinator)

        self._entity_description = entity_description
        self._is_available = False

        try:
            self.hass = hass
            self._item_id = item_id
            self._device_type = device_type

            device_info = coordinator.get_device_info(entity_description, item_id)

            entity_name = coordinator.get_entity_name(
                entity_description, device_info, item_id
            )

            unique_id = _build_unique_id(entity_description, item_id)

            self.entity_description = entity_description
            self._entity_description = entity_description

            self._attr_device_info = device_info
            self._attr_name = entity_name
            self._attr_unique_id = unique_id

            self._data = {}

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to initialize {entity_description}, Error: {ex}, Line: {line_number}"
            )

    @property
    def _local_coordinator(self) -> Coordinator:
        return self.coordinator

    @property
    def data(self) -> dict | None:
        return self._data

    @property
    def available(self) -> bool:
        return self._is_available

    def _get_is_available(self) -> bool:
        """Report the entity as unavailable while the router cannot be reached.

        Configuration entities hold Home Assistant side settings, they remain
        usable so that the integration can still be configured while the router
        is down.
        """
        if not self.coordinator.last_update_success:
            return False

        entity_description = self._entity_description

        if (
            entity_description is not None
            and entity_description.entity_category == EntityCategory.CONFIG
        ):
            return True

        return self._local_coordinator.is_connected

    async def async_execute_device_action(self, key: str, *kwargs: Any):
        async_device_action = self._local_coordinator.get_device_action(
            self._entity_description, self._item_id, key
        )

        # The coordinator has already reported why, and there is nothing to run
        if async_device_action is None:
            return

        if self._item_id is None:
            await async_device_action(self._entity_description, *kwargs)

        else:
            await async_device_action(self._entity_description, self._item_id, *kwargs)

        await self.coordinator.async_request_refresh()

    def update_component(self, data):
        pass

    def _refresh_name(self) -> bool:
        """Follow a name that comes from the item rather than the entity kind.

        A firewall rule is named after its description, so renaming the rule on
        the router has to rename the entity. Only those entities are checked -
        everything else is named after its kind, which cannot change while the
        entity exists.
        """
        if not self._entity_description.has_entity_name:
            return False

        name = self._local_coordinator.get_entity_name(
            self._entity_description, self._attr_device_info, self._item_id
        )

        if name is None or name == self._attr_name:
            return False

        self._attr_name = name

        return True

    def _handle_coordinator_update(self) -> None:
        """Fetch new state parameters for the sensor."""
        try:
            new_data = self._local_coordinator.get_data(
                self._entity_description, self._item_id
            )

            is_available = self._get_is_available()

            name_changed = self._refresh_name()

            # Availability is written as well, a router that went away does not
            # change the data and would otherwise keep reporting the last value
            if (
                self._data != new_data
                or self._is_available != is_available
                or name_changed
            ):
                self.update_component(new_data)

                self._data = new_data
                self._is_available = is_available

                self.async_write_ha_state()

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to update {self.unique_id}, Error: {ex}, Line: {line_number}"
            )
