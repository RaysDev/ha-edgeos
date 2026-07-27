import logging

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .common.base_entity import IntegrationBaseEntity, async_setup_base_entry
from .common.consts import (
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    ATTR_TITLE,
)
from .common.entity_descriptions import IntegrationUpdateEntityDescription
from .common.enums import DeviceTypes
from .managers.coordinator import Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    await async_setup_base_entry(
        hass,
        entry,
        Platform.UPDATE,
        IntegrationUpdateEntity,
        async_add_entities,
    )


class IntegrationUpdateEntity(IntegrationBaseEntity, UpdateEntity):
    """The router's firmware, as Home Assistant's own update entity.

    Reports only - installing is deliberately not offered. EdgeOS takes a
    firmware upgrade as a `.tar` uploaded to `upgrade.json`, so installing from
    here would mean fetching an image from Ubiquiti and pushing it to the
    router, and a flash that goes wrong leaves no router to recover with. That
    is not something to put behind a button in a system that runs unattended.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entity_description: IntegrationUpdateEntityDescription,
        coordinator: Coordinator,
        device_type: DeviceTypes,
        item_id: str | None,
    ):
        super().__init__(hass, entity_description, coordinator, device_type, item_id)

        self._attr_installed_version = None
        self._attr_latest_version = None

    def update_component(self, data):
        """Fetch new state parameters for the sensor."""
        if data is not None:
            self._attr_installed_version = data.get(ATTR_INSTALLED_VERSION)
            self._attr_latest_version = data.get(ATTR_LATEST_VERSION)
            self._attr_release_url = data.get(ATTR_RELEASE_URL)
            self._attr_title = data.get(ATTR_TITLE)

        else:
            self._attr_installed_version = None
            self._attr_latest_version = None
