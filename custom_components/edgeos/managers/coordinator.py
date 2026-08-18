import asyncio
from asyncio import sleep
from copy import copy
from datetime import datetime, timedelta
import logging
import sys
from time import monotonic
from typing import Callable

from homeassistant.components.device_tracker import ATTR_IP, ATTR_MAC
from homeassistant.components.homeassistant import SERVICE_RELOAD_CONFIG_ENTRY
from homeassistant.const import ATTR_STATE
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..common.connectivity_status import ConnectivityStatus
from ..common.consts import (
    ACTION_ENTITY_SELECT_OPTION,
    ACTION_ENTITY_SET_NATIVE_VALUE,
    ACTION_ENTITY_TURN_OFF,
    ACTION_ENTITY_TURN_ON,
    API_DATA_SYSTEM,
    ATTR_ACTIONS,
    ATTR_ATTRIBUTES,
    ATTR_HOSTNAME,
    ATTR_INSTALLED_VERSION,
    ATTR_IS_ON,
    ATTR_LAST_ACTIVITY,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    ATTR_TITLE,
    CONNECTION_WATCHDOG_INTERVAL,
    DEFAULT_NAME,
    DOMAIN,
    ENTITY_CONFIG_ENTRY_ID,
    HA_NAME,
    HEARTBEAT_INTERVAL,
    RECONNECT_INTERVAL_INVALID_CREDENTIALS,
    RECONNECT_INTERVAL_MAX,
    RECONNECT_INTERVAL_MIN,
    REMOVED_ITEM_GRACE_PERIOD,
    RETIRED_ENTITIES,
    SIGNAL_CONFIG_CHANGED,
    SIGNAL_DATA_CHANGED,
    SIGNAL_DEVICE_ADDED,
    SIGNAL_FIREWALL_RULE_ADDED,
    SIGNAL_INTERFACE_ADDED,
    SIGNAL_SYSTEM_ADDED,
    SIGNAL_WS_DATA_CHANGED,
    STABLE_CONNECTION_THRESHOLD,
    SUPERVISOR_STALL_TIMEOUT,
    SUPPORTED_REMOVED_ENTITIES_DEVICE_TYPES,
)
from ..common.entity_descriptions import PLATFORMS, IntegrationEntityDescription
from ..common.enums import DeviceTypes, EntityKeys
from ..data_processors.base_processor import BaseProcessor
from ..data_processors.device_processor import DeviceProcessor
from ..data_processors.firewall_processor import FirewallProcessor
from ..data_processors.interface_processor import InterfaceProcessor
from ..data_processors.system_processor import SystemProcessor
from ..models.edge_os_system_data import EdgeOSSystemData
from .config_manager import ConfigManager
from .rest_api import RestAPI
from .websockets import WebSockets

_LOGGER = logging.getLogger(__name__)


class Coordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    _api: RestAPI
    _websockets: WebSockets | None
    _processors: dict[DeviceTypes, BaseProcessor] | None = None

    _data_mapping: dict[
        str,
        Callable[[IntegrationEntityDescription], dict | None]
        | Callable[[IntegrationEntityDescription, str], dict | None],
    ] | None
    _system_status_details: dict | None

    _last_update: float
    _last_heartbeat: float

    def __init__(self, hass, config_manager: ConfigManager):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=config_manager.entry_title,
            update_interval=timedelta(seconds=config_manager.update_entities_interval),
            update_method=self._async_update_data,
        )

        _LOGGER.debug("Initializing")

        config_data = config_manager.config_data
        entry_id = config_manager.entry_id

        self._api = RestAPI(self.hass, config_data, entry_id)

        self._websockets = WebSockets(self.hass, config_data, entry_id)

        self._config_manager = config_manager

        self._data_mapping = None

        self._last_update = 0
        self._last_heartbeat = 0

        self._connection_task: asyncio.Task | None = None
        self._is_terminated: bool = False
        self._last_connected: float = 0
        self._last_supervisor_tick: float = 0
        self._config_refresh_requested: bool = False
        self._api_data_processed: bool = False
        self._missing_items: dict[str, float] = {}
        self._emptied_devices: dict[str, float] = {}

        self._can_load_components: bool = False

        self._system_processor = SystemProcessor(config_manager.config_data)
        self._device_processor = DeviceProcessor(config_manager.config_data)
        self._interface_processor = InterfaceProcessor(config_manager.config_data)
        self._firewall_processor = FirewallProcessor(config_manager.config_data)

        # A set: discovery is now checked against it for every item on every
        # streamed message, which is quadratic over a list
        self._discovered_objects: set[str] = set()

        self._processors = {
            DeviceTypes.SYSTEM: self._system_processor,
            DeviceTypes.DEVICE: self._device_processor,
            DeviceTypes.INTERFACE: self._interface_processor,
            DeviceTypes.FIREWALL_RULE: self._firewall_processor,
        }

        self._load_signal_handlers()

        _LOGGER.debug("Initializing done")

    @property
    def system(self) -> EdgeOSSystemData | None:
        system = self._system_processor.get()

        return system

    @property
    def api(self) -> RestAPI:
        api = self._api

        return api

    @property
    def websockets_data(self) -> dict:
        data = self._websockets.data

        return data

    @property
    def config_manager(self) -> ConfigManager:
        config_manager = self._config_manager

        return config_manager

    def _load_signal_handlers(self):
        @callback
        def on_data_changed(entry_id: str):
            # Tracked by Home Assistant, an untracked task can be garbage
            # collected while it is still running
            self.hass.async_create_task(self._on_data_changed(entry_id))

        @callback
        def on_ws_data_changed(entry_id: str):
            self.hass.async_create_task(self._on_ws_data_changed(entry_id))

        @callback
        def on_config_changed(entry_id: str):
            if entry_id != self._config_manager.entry_id:
                return

            _LOGGER.debug("Router reported a configuration change")

            # Acted on by the next update cycle, which both debounces a burst of
            # commits and keeps the fetch off the WebSocket callback path
            self._config_refresh_requested = True

        signal_handlers = {
            SIGNAL_DATA_CHANGED: on_data_changed,
            SIGNAL_WS_DATA_CHANGED: on_ws_data_changed,
            SIGNAL_CONFIG_CHANGED: on_config_changed,
        }

        _LOGGER.debug(f"Registering signals for {signal_handlers.keys()}")

        for signal in signal_handlers:
            handler = signal_handlers[signal]

            self._config_manager.entry.async_on_unload(
                async_dispatcher_connect(self.hass, signal, handler)
            )

    @property
    def is_connected(self) -> bool:
        """Whether both the API and the WebSocket are currently usable."""
        return (
            self._api.status == ConnectivityStatus.Connected
            and self._websockets.status == ConnectivityStatus.Connected
        )

    async def initialize(self):
        self._is_terminated = False

        self._build_data_mapping()

        self._remove_retired_entities()

        entry = self.config_manager.entry
        await self.hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        _LOGGER.info(f"Start loading {DOMAIN} integration, Entry ID: {entry.entry_id}")

        await self.async_request_refresh()

        # Connecting is intentionally not awaited, the integration must finish
        # loading even when the router is unreachable, so that it recovers on
        # its own once the router comes back
        self._ensure_connection_supervisor()

    def _remove_retired_entities(self):
        """Delete registry entries for entities this version no longer creates.

        Without this they stay behind as permanently unavailable, which is the
        kind of leftover the rest of this integration goes out of its way to
        avoid.
        """
        entity_registry = er.async_get(self.hass)

        for domain, unique_id in RETIRED_ENTITIES:
            entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)

            if entity_id is None:
                continue

            _LOGGER.info(f"Removing {entity_id}, Reason: it was replaced")

            entity_registry.async_remove(entity_id)

    async def terminate(self):
        self._is_terminated = True

        task = self._connection_task
        self._connection_task = None

        if task is not None and not task.done():
            task.cancel()

            try:
                await task

            except asyncio.CancelledError:
                pass

            except Exception as ex:
                _LOGGER.debug(f"Connection supervisor ended with an error: {ex}")

        await self._websockets.terminate()
        await self._api.terminate()

    def _ensure_connection_supervisor(self):
        """Start the connection supervisor unless it is already running."""
        if self._is_terminated:
            return

        task = self._connection_task

        if task is not None and not task.done():
            return

        if task is not None and not task.cancelled():
            # Surface why the previous supervisor stopped before replacing it
            exception = task.exception()

            if exception is not None:
                _LOGGER.error(
                    f"Connection supervisor stopped unexpectedly, Error: {exception}"
                )

        _LOGGER.debug("Starting connection supervisor")

        self._connection_task = self._config_manager.entry.async_create_background_task(
            self.hass, self._connection_supervisor(), f"{DOMAIN}_connection"
        )

    async def _connection_supervisor(self):
        """Keep the API session and the WebSocket alive, forever.

        Every disconnect, from any cause, ends up back at the top of this loop.
        The previous implementation reacted to individual status changes and had
        no handler for `Disconnected` or `NotFound`, so a router that was down
        when Home Assistant started, or that rebooted, left the integration idle
        until Home Assistant itself was restarted.
        """
        failures = 0

        while not self._is_terminated:
            self._last_supervisor_tick = monotonic()

            try:
                if self._api.status != ConnectivityStatus.Connected:
                    await self._api.initialize()

                if self._api.status == ConnectivityStatus.Connected:
                    await self._api.update()

                if self._api.status == ConnectivityStatus.Connected:
                    self._last_connected = monotonic()

                    self._websockets.update_api_data(
                        self._api.data, self._config_manager.log_incoming_messages
                    )

                    connected_at = monotonic()

                    # Returns once the WebSocket is gone
                    await self._websockets.initialize()

                    session_duration = monotonic() - connected_at

                    # A connection that lasted is a healthy one that simply
                    # dropped, reconnect promptly. One that ended immediately is
                    # a failed attempt and has to be backed off from, otherwise
                    # an unreachable WebSocket is retried every few seconds
                    # forever.
                    if session_duration >= STABLE_CONNECTION_THRESHOLD.total_seconds():
                        failures = 0

                    else:
                        failures += 1

                else:
                    failures += 1

            except asyncio.CancelledError:
                raise

            except Exception as ex:
                failures += 1

                exc_type, exc_obj, tb = sys.exc_info()
                line_number = tb.tb_lineno

                _LOGGER.error(
                    f"Connection attempt failed, Error: {ex}, Line: {line_number}"
                )

            if self._is_terminated:
                break

            await self._websockets.terminate()

            delay = self._get_reconnect_delay(failures)

            _LOGGER.debug(f"Reconnecting in {delay} seconds, Failures: {failures}")

            await sleep(delay)

        _LOGGER.debug("Connection supervisor stopped")

    def _get_reconnect_delay(self, failures: int) -> float:
        if self._api.status == ConnectivityStatus.InvalidCredentials:
            return RECONNECT_INTERVAL_INVALID_CREDENTIALS.total_seconds()

        minimum = RECONNECT_INTERVAL_MIN.total_seconds()
        maximum = RECONNECT_INTERVAL_MAX.total_seconds()

        # A single clean disconnect reconnects promptly, a router that stays
        # unreachable is backed off from so the log does not fill up
        delay = minimum * (2 ** max(failures - 1, 0))

        return min(delay, maximum)

    def get_debug_data(self) -> dict:
        config_data = self._config_manager.get_debug_data()

        data = {
            "config": config_data,
            "data": {
                "api": self._api.data,
                "websockets": self._websockets.data,
            },
            "processors": {
                DeviceTypes.DEVICE: self._device_processor.get_all(),
                DeviceTypes.INTERFACE: self._interface_processor.get_all(),
                DeviceTypes.FIREWALL_RULE: self._firewall_processor.get_all(),
                DeviceTypes.SYSTEM: self._system_processor.get().to_dict(),
            },
        }

        return data

    def _on_system_discovered(self) -> None:
        key = DeviceTypes.SYSTEM

        if key not in self._discovered_objects:
            self._discovered_objects.add(key)

            async_dispatcher_send(
                self.hass,
                SIGNAL_SYSTEM_ADDED,
                self._config_manager.entry_id,
                DeviceTypes.SYSTEM,
            )

    def _on_device_discovered(self, device_mac: str) -> None:
        key = f"{DeviceTypes.DEVICE} {device_mac}"

        if key not in self._discovered_objects:
            _LOGGER.info(f"Discovered device {device_mac}, Key: {key}")
            self._discovered_objects.add(key)

            # this triggers adding the sensors and the switch.
            async_dispatcher_send(
                self.hass,
                SIGNAL_DEVICE_ADDED,
                self._config_manager.entry_id,
                DeviceTypes.DEVICE,
                device_mac,
            )

    def _on_interface_discovered(self, interface_name: str) -> None:
        key = f"{DeviceTypes.INTERFACE} {interface_name}"

        if key not in self._discovered_objects:
            self._discovered_objects.add(key)

            async_dispatcher_send(
                self.hass,
                SIGNAL_INTERFACE_ADDED,
                self._config_manager.entry_id,
                DeviceTypes.INTERFACE,
                interface_name,
            )

    def _on_firewall_rule_discovered(self, rule_id: str) -> None:
        key = f"{DeviceTypes.FIREWALL_RULE} {rule_id}"

        if key not in self._discovered_objects:
            self._discovered_objects.add(key)

            async_dispatcher_send(
                self.hass,
                SIGNAL_FIREWALL_RULE_ADDED,
                self._config_manager.entry_id,
                DeviceTypes.FIREWALL_RULE,
                rule_id,
            )

    async def _on_data_changed(self, entry_id: str):
        """The API data was re-read, so everything is derived again."""
        if entry_id != self._config_manager.entry_id:
            return

        if not self.is_connected:
            return

        for processor in self._processors.values():
            processor.update(self._api.data, self._websockets.data)

        # From here on the statistics can be processed on their own
        self._api_data_processed = True

        if not self._discover():
            return

        self._forget_removed_firewall_rules(self._firewall_processor.get_rules())

    async def _on_ws_data_changed(self, entry_id: str):
        """A statistics message arrived, so only the statistics are derived.

        These messages carry no configuration, so re-deriving it here would
        produce the same answer it did a fraction of a second earlier - at the
        cost of walking every interface, DHCP lease and firewall rule, once or
        twice a second, forever.
        """
        if entry_id != self._config_manager.entry_id:
            return

        if not self.is_connected:
            return

        if not self._api_data_processed:
            # Nothing has derived the configuration yet, and the statistics are
            # attached to what that leaves behind
            await self._on_data_changed(entry_id)

            return

        for processor in self._processors.values():
            processor.update_ws_data(self._websockets.data)

        # Interfaces the configuration does not mention, `pppoe0` and the like,
        # are only ever discovered from this stream
        self._discover()

    def _discover(self) -> bool:
        """Announce whatever the platforms have not been told about yet.

        Returns whether the router is known well enough to have discovered
        anything at all.
        """
        system = self._system_processor.get()

        if system is None or system.hostname is None:
            return False

        self._on_system_discovered()

        for interface_name in self._interface_processor.get_interfaces():
            interface = self._interface_processor.get_data(interface_name)

            if interface.is_supported:
                self._on_interface_discovered(interface_name)

        for device_mac in self._device_processor.get_devices():
            device = self._device_processor.get_data(device_mac)

            if not device.is_leased:
                self._on_device_discovered(device_mac)

        for rule_id in self._firewall_processor.get_rules():
            self._on_firewall_rule_discovered(rule_id)

        return True

    def _forget_removed_firewall_rules(self, rule_ids: list[str]):
        """Allow a rule that comes back to be discovered again.

        Only the bookkeeping, the device itself is removed by
        `_async_sync_firewall_rule_devices` once the removal has been confirmed.
        """
        prefix = f"{DeviceTypes.FIREWALL_RULE} "

        stale_keys = [
            key
            for key in self._discovered_objects
            if key.startswith(prefix) and key[len(prefix) :] not in rule_ids
        ]

        for key in stale_keys:
            self._discovered_objects.remove(key)

    async def _async_sync_firewall_rule_devices(self):
        """Keep the rule-set devices in step with the router.

        Renames a device whose rule-set was renamed, and deletes one whose
        rule-set is gone. Driven by the device registry rather than by what was
        discovered in this session, so that a rule-set deleted while Home
        Assistant was not running is cleaned up too, instead of lingering as a
        permanently unavailable device.

        Devices left by a version that gave every rule its own device are
        matched here as well. Their identifier can never be valid now, so they
        are removed like anything else that disappeared - and the grace period
        below is what gives their entities time to re-home onto the rule-set
        device first.
        """
        system_section = self._api.data.get(API_DATA_SYSTEM)

        # Nothing to compare against until a configuration has been read
        if not isinstance(system_section, dict) or not system_section:
            return

        valid_devices = {}

        for rule_id in self._firewall_processor.get_rules():
            identifier = self._get_device_identifier(self._firewall_processor, rule_id)

            if identifier is not None:
                valid_devices[identifier] = rule_id

        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        devices = dr.async_entries_for_config_entry(
            device_registry, self._config_manager.entry_id
        )

        firewall_models = [
            str(DeviceTypes.FIREWALL_RULESET),
            str(DeviceTypes.FIREWALL_RULE),
        ]

        now = monotonic()
        missing = {}

        for device in devices:
            if device.model not in firewall_models:
                continue

            identifier = next(
                (item[1] for item in device.identifiers if item[0] == DEFAULT_NAME),
                None,
            )

            if identifier is None:
                continue

            rule_id = valid_devices.get(identifier)

            if rule_id is not None:
                self._sync_device_name(device_registry, device, rule_id)

                continue

            first_missing = self._missing_items.get(identifier, now)
            missing[identifier] = first_missing

            if now - first_missing < REMOVED_ITEM_GRACE_PERIOD.total_seconds():
                continue

            _LOGGER.info(
                f"Removing {device.name}, "
                f"Reason: the firewall rule-set is no longer configured on the router"
            )

            for entity in entity_registry.entities.get_entries_for_device_id(device.id):
                entity_registry.async_remove(entity.entity_id)

            device_registry.async_remove_device(device.id)

            missing.pop(identifier, None)

        # Anything that reappeared stops being a candidate for removal
        self._missing_items = missing

    async def _async_remove_emptied_devices(self):
        """Delete a device once nothing points at it any more.

        A device exists only because an entity references it. Turning monitoring
        off takes away every entity a device had, and upgrading moves the
        monitoring toggle onto the shared device, so in both cases what is left
        behind is a device that displays nothing at all.

        The condition is deliberately narrow - no entity registry entries -
        because such a device cannot be showing the user anything. Disabled
        entities still count as entries, so disabling them rather than turning
        monitoring off will not remove anything.
        """
        system_section = self._api.data.get(API_DATA_SYSTEM)

        # Nothing has been read yet, so nothing has had a chance to be created
        if not isinstance(system_section, dict) or not system_section:
            return

        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        devices = dr.async_entries_for_config_entry(
            device_registry, self._config_manager.entry_id
        )

        now = monotonic()
        emptied = {}

        for device in devices:
            if device.model != str(DeviceTypes.DEVICE):
                continue

            if entity_registry.entities.get_entries_for_device_id(device.id):
                continue

            first_emptied = self._emptied_devices.get(device.id, now)
            emptied[device.id] = first_emptied

            # The grace period is what lets entities finish being added at
            # startup before their device is judged empty
            if now - first_emptied < REMOVED_ITEM_GRACE_PERIOD.total_seconds():
                continue

            _LOGGER.info(f"Removing {device.name}, Reason: it has no entities left")

            device_registry.async_remove_device(device.id)

            emptied.pop(device.id, None)

        self._emptied_devices = emptied

    def _sync_device_name(self, device_registry, device, rule_id: str):
        """Follow a rule-set renamed on the router.

        Only the name the integration supplies is touched. A device the user
        renamed keeps their name, which Home Assistant holds separately.
        """
        device_info = self._firewall_processor.get_device_info(rule_id)
        name = device_info.get("name")

        if not name or name == device.name:
            return

        _LOGGER.info(f"Renaming {device.name} to {name}")

        device_registry.async_update_device(device.id, name=name)

    @staticmethod
    def _get_device_identifier(processor: BaseProcessor, item_id: str) -> str | None:
        device_info = processor.get_device_info(item_id)
        identifiers = device_info.get("identifiers", set())

        return next(
            (item[1] for item in identifiers if item[0] == DEFAULT_NAME),
            None,
        )

    async def _async_update_data(self):
        """Fetch parameters from API endpoint.

        This is the place to pre-process the parameters to lookup tables
        so entities can quickly look up their parameters.
        """
        try:
            _LOGGER.debug("Updating data")

            now = monotonic()

            # Last line of defence, if the supervisor ever stops - an unexpected
            # exception, a cancelled task - this restarts it
            self._ensure_connection_supervisor()

            if self.is_connected:
                self._last_connected = now

                if now - self._last_heartbeat >= HEARTBEAT_INTERVAL.total_seconds():
                    await self._websockets.send_heartbeat()

                    self._last_heartbeat = now

                is_due = (
                    now - self._last_update >= self.config_manager.update_api_interval
                )

                if is_due:
                    self._config_refresh_requested = False

                    await self._api.update()

                    self._last_update = now

                    await self._on_data_changed(self.config_manager.entry_id)

                    await self._async_sync_firewall_rule_devices()

                    await self._async_remove_emptied_devices()

                elif self._config_refresh_requested:
                    # A commit happened on the router, re-read the configuration
                    # now rather than waiting for the next scheduled poll
                    self._config_refresh_requested = False

                    await self._api.refresh_configuration()

                    await self._on_data_changed(self.config_manager.entry_id)

                    # Only ever after a fresh read of the configuration, never on
                    # the cached copy that the websocket messages are processed
                    # against
                    await self._async_sync_firewall_rule_devices()

                    await self._async_remove_emptied_devices()

            else:
                await self._recover_broken_api()

                self._check_connection_watchdog(now)

            return {}

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _recover_broken_api(self):
        """Rebuild the session when only the API half of it is broken.

        A single failed request marks the API as disconnected, but the
        connection supervisor is parked on the WebSocket and only logs in again
        once that ends. Closing the WebSocket releases it, so a transient REST
        failure costs one reconnect instead of leaving every entity unavailable
        until the stall watchdog notices, up to `SUPERVISOR_STALL_TIMEOUT`
        later.
        """
        api_status = self._api.status

        if api_status in [
            ConnectivityStatus.Connected,
            ConnectivityStatus.Connecting,
        ]:
            return

        if self._websockets.status != ConnectivityStatus.Connected:
            return

        _LOGGER.warning(
            f"API is not connected ({api_status}) while the WebSocket still is, "
            f"closing the WebSocket so that the connection is rebuilt"
        )

        await self._websockets.async_disconnect()

    def _check_connection_watchdog(self, now: float):
        """Report a prolonged disconnect, and restart a supervisor that stalled.

        The supervisor is expected to come back around its loop at least every
        `RECONNECT_INTERVAL_MAX`. If it has not, something is blocking that
        should not be, and it is replaced rather than left wedged.
        """
        if self._last_connected == 0:
            self._last_connected = now

        disconnected_for = now - self._last_connected

        if disconnected_for >= CONNECTION_WATCHDOG_INTERVAL.total_seconds():
            self._last_connected = now

            _LOGGER.warning(
                f"Not connected for {int(disconnected_for)} seconds, "
                f"API: {self._api.status}, "
                f"WebSocket: {self._websockets.status}"
            )

        task = self._connection_task

        if task is None or task.done() or self._last_supervisor_tick == 0:
            return

        stalled_for = now - self._last_supervisor_tick

        if stalled_for < SUPERVISOR_STALL_TIMEOUT.total_seconds():
            return

        _LOGGER.error(
            f"Connection supervisor made no progress for {int(stalled_for)} seconds, "
            f"restarting it"
        )

        self._last_supervisor_tick = now

        # Replaced on the next update by `_ensure_connection_supervisor`
        task.cancel()

    def _build_data_mapping(self):
        _LOGGER.debug("Building data mappers")

        data_mapping = {
            EntityKeys.CPU_USAGE: self._get_cpu_usage_data,
            EntityKeys.RAM_USAGE: self._get_ram_usage_data,
            EntityKeys.FIRMWARE: self._get_firmware_data,
            EntityKeys.LAST_RESTART: self._get_last_restart_data,
            EntityKeys.UNKNOWN_DEVICES: self._get_unknown_devices_data,
            EntityKeys.LOG_INCOMING_MESSAGES: self._get_log_incoming_messages_data,
            EntityKeys.CONSIDER_AWAY_INTERVAL: self._get_consider_away_interval_data,
            EntityKeys.UPDATE_ENTITIES_INTERVAL: self._get_update_entities_interval_data,
            EntityKeys.UPDATE_API_INTERVAL: self._get_update_api_interval_data,
            EntityKeys.UNIT: self._get_unit_data,
            EntityKeys.INTERFACE_CONNECTED: self._get_interface_connected_data,
            EntityKeys.INTERFACE_RECEIVED_DROPPED: self._get_interface_received_dropped_data,
            EntityKeys.INTERFACE_SENT_DROPPED: self._get_interface_sent_dropped_data,
            EntityKeys.INTERFACE_RECEIVED_ERRORS: self._get_interface_received_errors_data,
            EntityKeys.INTERFACE_SENT_ERRORS: self._get_interface_sent_errors_data,
            EntityKeys.INTERFACE_RECEIVED_PACKETS: self._get_interface_received_packets_data,
            EntityKeys.INTERFACE_SENT_PACKETS: self._get_interface_sent_packets_data,
            EntityKeys.INTERFACE_RECEIVED_RATE: self._get_interface_received_rate_data,
            EntityKeys.INTERFACE_SENT_RATE: self._get_interface_sent_rate_data,
            EntityKeys.INTERFACE_RECEIVED_TRAFFIC: self._get_interface_received_traffic_data,
            EntityKeys.INTERFACE_SENT_TRAFFIC: self._get_interface_sent_traffic_data,
            EntityKeys.INTERFACE_MONITORED: self._get_interface_monitored_data,
            EntityKeys.INTERFACE_STATUS: self._get_interface_status_data,
            EntityKeys.DEVICE_RECEIVED_RATE: self._get_device_received_rate_data,
            EntityKeys.DEVICE_SENT_RATE: self._get_device_sent_rate_data,
            EntityKeys.DEVICE_RECEIVED_TRAFFIC: self._get_device_received_traffic_data,
            EntityKeys.DEVICE_SENT_TRAFFIC: self._get_device_sent_traffic_data,
            EntityKeys.DEVICE_TRACKER: self._get_device_tracker_data,
            EntityKeys.DEVICE_MONITORED: self._get_device_monitored_data,
            EntityKeys.FIREWALL_RULE_STATUS: self._get_firewall_rule_status_data,
        }

        self._data_mapping = data_mapping

    def get_device_info(
        self,
        entity_description: IntegrationEntityDescription,
        item_id: str | None = None,
    ) -> DeviceInfo:
        processor = self._processors[entity_description.device_type]

        if entity_description.on_shared_device:
            shared_device_info = processor.get_shared_device_info()

            if shared_device_info is not None:
                return shared_device_info

        return processor.get_device_info(item_id)

    def get_entity_name(
        self,
        entity_description: IntegrationEntityDescription,
        device_info: DeviceInfo,
        item_id: str | None = None,
    ) -> str | None:
        """Name an entity, letting the processor name it per item if it can.

        A firewall rule-set holds one entity per rule, so there the name comes
        from the rule rather than from the entity description. Everything else
        keeps naming an entity after its kind.
        """
        if entity_description.has_entity_name:
            processor = self._processors[entity_description.device_type]

            item_name = processor.get_item_name(item_id)

            if item_name is not None:
                return item_name

        return self._config_manager.get_entity_name(entity_description, device_info)

    def get_data(
        self,
        entity_description: IntegrationEntityDescription,
        item_id: str | None = None,
    ) -> dict | None:
        result = None

        try:
            handler = self._data_mapping.get(entity_description.key)

            if handler is None:
                _LOGGER.warning(
                    f"Handler was not found for {entity_description.key}, Entity Description: {entity_description}"
                )

            else:
                if item_id is None:
                    result = handler(entity_description)

                else:
                    result = handler(entity_description, item_id)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract data for {entity_description}, Error: {ex}, Line: {line_number}"
            )

        return result

    def get_device_identifiers(
        self, device_type: DeviceTypes, item_id: str | None = None
    ) -> set[tuple[str, str]]:
        if device_type == DeviceTypes.DEVICE:
            device_info = self._device_processor.get_device_info(item_id)

        elif device_type == DeviceTypes.INTERFACE:
            device_info = self._interface_processor.get_device_info(item_id)

        elif device_type == DeviceTypes.FIREWALL_RULE:
            device_info = self._firewall_processor.get_device_info(item_id)

        else:
            device_info = self._system_processor.get_device_info()

        identifiers = device_info.get("identifiers")

        return identifiers

    def get_device_data(self, model: str, identifiers: set[tuple[str, str]]):
        if model == str(DeviceTypes.DEVICE):
            device_data = self._device_processor.get_device(identifiers)

        elif model == str(DeviceTypes.INTERFACE):
            device_data = self._interface_processor.get_interface(identifiers)

        elif model == str(DeviceTypes.FIREWALL_RULESET):
            device_data = self._firewall_processor.get_firewall_rule(identifiers)

        else:
            device_data = self._system_processor.get().to_dict()

        return device_data

    def get_device_action(
        self,
        entity_description: IntegrationEntityDescription,
        monitor_id: str | None,
        action_key: str,
    ) -> Callable | None:
        device_data = self.get_data(entity_description, monitor_id)

        # An item removed from the router reports no data, which used to raise
        # here - pressing the switch of a firewall rule deleted moments earlier
        # is the reachable case
        actions = {} if device_data is None else device_data.get(ATTR_ACTIONS, {})

        async_action = actions.get(action_key)

        if async_action is None:
            _LOGGER.warning(
                f"Action {action_key} is not available for "
                f"{entity_description.key}"
                f"{'' if monitor_id is None else f' of {monitor_id}'}"
            )

        return async_action

    @staticmethod
    def _get_date_time_from_timestamp(timestamp):
        result = datetime.fromtimestamp(timestamp)

        return result

    def _get_cpu_usage_data(self, _entity_description) -> dict | None:
        data = self._system_processor.get()

        result = {
            ATTR_STATE: data.cpu,
        }

        return result

    def _get_ram_usage_data(self, _entity_description) -> dict | None:
        data = self._system_processor.get()

        result = {
            ATTR_STATE: data.mem,
        }

        return result

    def _get_firmware_data(self, _entity_description) -> dict | None:
        data = self._system_processor.get()

        installed = data.sw_version or data.fw_version

        if data.upgrade_available:
            latest = data.upgrade_version

        elif data.upgrade_state is None:
            # The router has not checked. That is not the same as being up to
            # date, and reporting it as such would be a false reassurance, so
            # the version is left unknown instead.
            latest = None

        else:
            latest = installed

        return {
            ATTR_INSTALLED_VERSION: installed,
            ATTR_LATEST_VERSION: latest,
            ATTR_RELEASE_URL: data.upgrade_url,
            ATTR_TITLE: data.product,
        }

    def _get_last_restart_data(self, _entity_description) -> dict | None:
        data = self._system_processor.get()

        tz = datetime.now().astimezone().tzinfo
        state = datetime.fromtimestamp(data.last_reset.timestamp(), tz=tz)

        result = {ATTR_STATE: state}

        return result

    def _get_unknown_devices_data(self, _entity_description) -> dict | None:
        leased_devices = self._device_processor.get_leased_devices()

        result = {
            ATTR_STATE: len(leased_devices.keys()),
            ATTR_ATTRIBUTES: leased_devices,
        }

        return result

    def _get_log_incoming_messages_data(self, _entity_description) -> dict | None:
        result = {
            ATTR_IS_ON: self.config_manager.log_incoming_messages,
            ATTR_ACTIONS: {
                ACTION_ENTITY_TURN_ON: self._set_log_incoming_messages_enabled,
                ACTION_ENTITY_TURN_OFF: self._set_log_incoming_messages_disabled,
            },
        }

        return result

    def _get_consider_away_interval_data(self, _entity_description) -> dict | None:
        result = {
            ATTR_STATE: self.config_manager.consider_away_interval,
            ATTR_ACTIONS: {
                ACTION_ENTITY_SET_NATIVE_VALUE: self._set_consider_away_interval,
            },
        }

        return result

    def _get_update_entities_interval_data(self, _entity_description) -> dict | None:
        result = {
            ATTR_STATE: self.config_manager.update_entities_interval,
            ATTR_ACTIONS: {
                ACTION_ENTITY_SET_NATIVE_VALUE: self._set_update_entities_interval,
            },
        }

        return result

    def _get_update_api_interval_data(self, _entity_description) -> dict | None:
        result = {
            ATTR_STATE: self.config_manager.update_api_interval,
            ATTR_ACTIONS: {
                ACTION_ENTITY_SET_NATIVE_VALUE: self._set_update_api_interval,
            },
        }

        return result

    def _get_unit_data(self, _entity_description) -> dict | None:
        result = {
            ATTR_STATE: self.config_manager.unit,
            ATTR_ACTIONS: {
                ACTION_ENTITY_SELECT_OPTION: self._set_unit,
            },
        }

        return result

    def _get_interface_connected_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_IS_ON: interface.l1up}

        return result

    def _get_interface_received_dropped_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.received.dropped}

        return result

    def _get_interface_sent_dropped_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.sent.dropped}

        return result

    def _get_interface_received_errors_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.received.errors}

        return result

    def _get_interface_sent_errors_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.sent.errors}

        return result

    def _get_interface_received_packets_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.received.packets}

        return result

    def _get_interface_sent_packets_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.sent.packets}

        return result

    def _get_interface_received_rate_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.received.rate}

        return result

    def _get_interface_sent_rate_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.sent.rate}

        return result

    def _get_interface_received_traffic_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.received.total}

        return result

    def _get_interface_sent_traffic_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)

        result = {ATTR_STATE: interface.sent.total}

        return result

    def _get_interface_monitored_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        state = self.config_manager.get_monitored_interface(interface_name)

        result = {
            ATTR_IS_ON: state,
            ATTR_ACTIONS: {
                ACTION_ENTITY_TURN_ON: self._set_interface_monitor_enabled,
                ACTION_ENTITY_TURN_OFF: self._set_interface_monitor_disabled,
            },
        }

        return result

    def _get_interface_status_data(
        self, _entity_description, interface_name: str
    ) -> dict | None:
        interface = self._interface_processor.get_data(interface_name)
        interface_attributes = interface.get_attributes()

        result = {
            ATTR_IS_ON: interface.up,
            ATTR_ATTRIBUTES: interface_attributes,
            ATTR_ACTIONS: {
                ACTION_ENTITY_TURN_ON: self._set_interface_enabled,
                ACTION_ENTITY_TURN_OFF: self._set_interface_disabled,
            },
        }

        return result

    def _get_device_received_rate_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        device = self._device_processor.get_data(device_mac)

        result = {ATTR_STATE: device.received.rate}

        return result

    def _get_device_sent_rate_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        device = self._device_processor.get_data(device_mac)

        result = {ATTR_STATE: device.sent.rate}

        return result

    def _get_device_received_traffic_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        device = self._device_processor.get_data(device_mac)

        result = {ATTR_STATE: device.received.total}

        return result

    def _get_device_sent_traffic_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        device = self._device_processor.get_data(device_mac)

        result = {ATTR_STATE: device.sent.total}

        return result

    def _get_device_tracker_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        device = self._device_processor.get_data(device_mac)
        consider_away_interval = self.config_manager.consider_away_interval
        last_activity = self._get_date_time_from_timestamp(device.last_activity)
        is_on = consider_away_interval >= device.last_activity_in_seconds

        result = {
            ATTR_IS_ON: is_on,
            ATTR_ATTRIBUTES: {
                ATTR_LAST_ACTIVITY: last_activity,
                ATTR_IP: device.ip,
                ATTR_MAC: device.mac,
                ATTR_HOSTNAME: device.hostname,
            },
        }

        return result

    def _get_device_monitored_data(
        self, _entity_description, device_mac: str
    ) -> dict | None:
        state = self.config_manager.get_monitored_device(device_mac)
        device = self._device_processor.get_data(device_mac)
        device_attributes = device.get_attributes()

        result = {
            ATTR_IS_ON: state,
            ATTR_ATTRIBUTES: device_attributes,
            ATTR_ACTIONS: {
                ACTION_ENTITY_TURN_ON: self._set_device_monitor_enabled,
                ACTION_ENTITY_TURN_OFF: self._set_device_monitor_disabled,
            },
        }

        return result

    def _get_firewall_rule_status_data(
        self, _entity_description, rule_id: str
    ) -> dict | None:
        rule = self._firewall_processor.get_data(rule_id)

        # The rule may have been removed from the router's configuration
        if rule is None:
            return None

        rule_attributes = rule.get_attributes()

        result = {
            ATTR_IS_ON: rule.is_enabled,
            ATTR_ATTRIBUTES: rule_attributes,
            ATTR_ACTIONS: {
                ACTION_ENTITY_TURN_ON: self._set_firewall_rule_enabled,
                ACTION_ENTITY_TURN_OFF: self._set_firewall_rule_disabled,
            },
        }

        return result

    async def _set_firewall_rule_enabled(self, _entity_description, rule_id: str):
        await self._set_firewall_rule_state(rule_id, True)

    async def _set_firewall_rule_disabled(self, _entity_description, rule_id: str):
        await self._set_firewall_rule_state(rule_id, False)

    async def _set_firewall_rule_state(self, rule_id: str, is_enabled: bool):
        _LOGGER.debug(f"Set state of firewall rule {rule_id} to {is_enabled}")

        rule = self._firewall_processor.get_data(rule_id)

        if rule is None:
            _LOGGER.error(
                f"Failed to set state of firewall rule {rule_id}, "
                f"Reason: rule is no longer configured"
            )

            return

        modified = await self._api.set_firewall_rule_state(rule, is_enabled)

        if modified:
            self._firewall_processor.set_pending_state(rule_id, is_enabled)

        # The router announces the commit over the WebSocket, this covers the
        # case where the WebSocket is not connected at that moment
        self._request_configuration_refresh()

    def _request_configuration_refresh(self):
        self._config_refresh_requested = True

    async def _set_interface_enabled(self, _entity_description, interface_name: str):
        _LOGGER.debug(f"Enable interface {interface_name}")
        interface = self._interface_processor.get_data(interface_name)

        await self._api.set_interface_state(interface, True)

        self._request_configuration_refresh()

    async def _set_interface_disabled(self, _entity_description, interface_name: str):
        _LOGGER.debug(f"Disable interface {interface_name}")
        interface = self._interface_processor.get_data(interface_name)

        await self._api.set_interface_state(interface, False)

        self._request_configuration_refresh()

    async def _set_interface_monitor_enabled(
        self, _entity_description, interface_name: str
    ):
        _LOGGER.debug(f"Enable monitoring for interface {interface_name}")

        await self._config_manager.set_monitored_interface(interface_name, True)

        await self._remove_entities_of_device(DeviceTypes.INTERFACE, interface_name)

    async def _set_interface_monitor_disabled(
        self, _entity_description, interface_name: str
    ):
        _LOGGER.debug(f"Disable monitoring for interface {interface_name}")

        await self._config_manager.set_monitored_interface(interface_name, False)

        await self._remove_entities_of_device(DeviceTypes.INTERFACE, interface_name)

    async def _set_device_monitor_enabled(self, _entity_description, device_mac: str):
        _LOGGER.debug(f"Enable monitoring for device {device_mac}")

        await self._config_manager.set_monitored_device(device_mac, True)

        await self._remove_entities_of_device(DeviceTypes.DEVICE, device_mac)

    async def _set_device_monitor_disabled(self, _entity_description, device_mac: str):
        _LOGGER.debug(f"Disable monitoring for device {device_mac}")

        await self._config_manager.set_monitored_device(device_mac, False)

        await self._remove_entities_of_device(DeviceTypes.DEVICE, device_mac)

    async def _set_log_incoming_messages_enabled(self, _entity_description):
        _LOGGER.debug("Enable log incoming messages")

        await self._config_manager.set_log_incoming_messages(True)

        self._websockets.update_api_data(
            self._api.data, self.config_manager.log_incoming_messages
        )

    async def _set_log_incoming_messages_disabled(self, _entity_description):
        _LOGGER.debug("Disable log incoming messages")

        await self._config_manager.set_log_incoming_messages(False)

        self._websockets.update_api_data(
            self._api.data, self.config_manager.log_incoming_messages
        )

    async def _set_consider_away_interval(self, _entity_description, value: int):
        _LOGGER.debug("Disable log incoming messages")

        await self._config_manager.set_consider_away_interval(value)

    async def _set_update_entities_interval(self, _entity_description, value: int):
        _LOGGER.debug("Change update entities interval")

        await self._config_manager.set_update_entities_interval(value)

        await self._reload_integration()

    async def _set_update_api_interval(self, _entity_description, value: int):
        _LOGGER.debug("Change update API interval")

        await self._config_manager.set_update_api_interval(value)

        await self._reload_integration()

    async def _set_unit(self, _entity_description, option: str):
        _LOGGER.debug("Change unit settings")

        await self._config_manager.set_unit(option)

        await self._remove_entities_of_device()

    async def _remove_entities_of_device(
        self, device_type: DeviceTypes | None = None, item_id: str | None = None
    ):
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        handle_device_types = (
            SUPPORTED_REMOVED_ENTITIES_DEVICE_TYPES
            if device_type is None
            else [device_type]
        )
        handle_items = None if item_id is None else [item_id]

        if (
            device_type is not None
            and device_type not in SUPPORTED_REMOVED_ENTITIES_DEVICE_TYPES
        ):
            return

        for device_type_item in handle_device_types:
            processor = self._processors[device_type_item]

            if handle_items is None:
                monitored_items = copy(
                    self._config_manager.get_monitored_items(device_type_item)
                )

                handle_items = [
                    monitored_item
                    for monitored_item in monitored_items
                    if monitored_items[monitored_item]
                ]

            for handle_item_id in handle_items:
                key = f"{device_type_item} {handle_item_id}"

                device_info = processor.get_device_info(handle_item_id)

                _LOGGER.debug(f"Refreshing {device_type_item} {key}: {device_info}")

                device_info_identifier = device_info.get("identifiers")
                device_data = device_registry.async_get_device(
                    identifiers=device_info_identifier
                )

                if device_data is not None:
                    entities = entity_registry.entities.get_entries_for_device_id(
                        device_data.id
                    )
                    for entity in entities:
                        _LOGGER.info(f"Removing entity {entity.entity_id}")
                        entity_registry.async_remove(entity.entity_id)

                    device_id = next( (item[1] for item in device_data.identifiers if item[0] == DEFAULT_NAME), None,)
                    _LOGGER.info(f"Removing device {device_id}")
                    device_registry.async_remove_device(device_data.id)

                if key in self._discovered_objects:
                    self._discovered_objects.remove(key)

            handle_items = None

        # The entities have just been unregistered and their discovery keys
        # dropped, but `async_refresh` alone does not re-run discovery unless a
        # poll happens to be due - which left them missing for up to a whole
        # `update_api_interval` after the user flipped a switch
        self._request_configuration_refresh()

        await self.async_refresh()

    async def _reload_integration(self):
        data = {ENTITY_CONFIG_ENTRY_ID: self.config_manager.entry_id}

        await self.hass.services.async_call(HA_NAME, SERVICE_RELOAD_CONFIG_ENTRY, data)
