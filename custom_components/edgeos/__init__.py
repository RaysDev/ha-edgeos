"""
This component provides support for EdgeOS based devices.
For more details about this component, please refer to the documentation at
https://github.com/blchinezu/ha-edgeos
"""
import logging
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .common.consts import DEFAULT_NAME, DOMAIN
from .common.entity_descriptions import PLATFORMS
from .managers.config_manager import ConfigManager
from .managers.coordinator import Coordinator
from .managers.password_manager import PasswordManager
from .models.exceptions import LoginError

_LOGGER = logging.getLogger(__name__)


async def async_setup(_hass, _config):
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a EdgeOS component."""
    initialized = False

    try:
        _LOGGER.debug("Setting up")
        entry_config = {key: entry.data[key] for key in entry.data}

        _LOGGER.debug("Starting up password manager")
        await PasswordManager.decrypt(hass, entry_config, entry.entry_id)

        _LOGGER.debug("Starting up configuration manager")
        config_manager = ConfigManager(hass, entry)
        await config_manager.initialize(entry_config)

        is_initialized = config_manager.is_initialized

        if is_initialized:
            _LOGGER.debug("Starting up coordinator")
            coordinator = Coordinator(hass, config_manager)

            hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

            # Initializing does not perform any network access, it sets the
            # platforms up and hands the connection over to a background
            # supervisor. Waiting for `EVENT_HOMEASSISTANT_START` instead used to
            # mean that anything that made that event handler fail left the
            # integration loaded but permanently idle.
            _LOGGER.debug("Initializing coordinator")
            await coordinator.initialize()

            _LOGGER.info("Finished loading integration")

        initialized = is_initialized

        _LOGGER.debug(f"Setup status: {is_initialized}")

    except LoginError:
        _LOGGER.info(f"Failed to login {DEFAULT_NAME} API, cannot log integration")

    except Exception as ex:
        exc_type, exc_obj, tb = sys.exc_info()
        line_number = tb.tb_lineno

        _LOGGER.error(
            f"Failed to load {DEFAULT_NAME}, error: {ex}, line: {line_number}"
        )

    return initialized


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.info(f"Unloading {DOMAIN} integration, Entry ID: {entry.entry_id}")

    coordinator: Coordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    # Stop the connection supervisor before the platforms go away, otherwise it
    # keeps reconnecting into a half unloaded integration and the reload ends up
    # with two connections fighting over the same entry
    if coordinator is not None:
        try:
            await coordinator.terminate()

        except Exception as ex:
            _LOGGER.warning(f"Failed to terminate coordinator cleanly, Error: {ex}")

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.info(f"Removing {DOMAIN} integration, Entry ID: {entry.entry_id}")

    entry_id = entry.entry_id

    coordinator: Coordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)

    if coordinator is not None:
        await coordinator.config_manager.remove(entry_id)

    result = await async_unload_entry(hass, entry)

    return result
