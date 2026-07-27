from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
import json
import logging
import re
import sys
from typing import Any, Callable

import aiohttp
from aiohttp import ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import dispatcher_send

from ..common.connectivity_status import ConnectivityStatus
from ..common.consts import (
    ADDRESS_HW_ADDR,
    ADDRESS_IPV4,
    ADDRESS_LIST,
    API_DATA_COOKIES,
    API_DATA_LAST_UPDATE,
    API_DATA_SESSION_ID,
    BEGINS_WITH_SIX_DIGITS,
    CONFIG_CHANGE_COMMIT,
    CONFIG_CHANGE_COMMIT_ENDED,
    DEFAULT_NAME,
    DEVICE_LIST,
    DISCONNECT_INTERVAL,
    DISCOVER_DEVICE_ITEMS,
    EMPTY_STRING,
    INTERFACE_DATA_MULTICAST,
    INTERFACES_MAIN_MAP,
    INTERFACES_STATS,
    SIGNAL_CONFIG_CHANGED,
    SIGNAL_WS_DATA_CHANGED,
    SIGNAL_WS_STATUS,
    STRING_COLON,
    STRING_COMMA,
    TRAFFIC_DATA_DEVICE_ITEMS,
    TRAFFIC_DATA_DIRECTIONS,
    TRAFFIC_DATA_INTERFACE_ITEMS,
    WS_CLOSE_TIMEOUT,
    WS_CLOSING_MESSAGE,
    WS_COMPRESSION_DEFLATE,
    WS_CONFIG_CHANGE_KEY,
    WS_CONNECT_TIMEOUT,
    WS_DISCOVER_KEY,
    WS_EXPORT_KEY,
    WS_IGNORED_MESSAGES,
    WS_INTERFACES_KEY,
    WS_MAX_MSG_SIZE,
    WS_RECEIVE_TIMEOUT,
    WS_RECEIVED_MESSAGES,
    WS_SESSION_ID,
    WS_SYSTEM_STATS_KEY,
    WS_TOPIC_NAME,
    WS_TOPIC_SUBSCRIBE,
    WS_TOPIC_UNSUBSCRIBE,
)
from ..models.config_data import ConfigData

_LOGGER = logging.getLogger(__name__)


class WebSockets:
    _hass: HomeAssistant | None
    _session: ClientSession | None
    _triggered_sensors: dict
    _api_data: dict
    _config_data: ConfigData
    _entry_id: str | None

    _status: ConnectivityStatus | None
    _on_status_changed: Callable[[ConnectivityStatus], Awaitable[None]]
    _previous_message: dict | None

    def __init__(
        self, hass: HomeAssistant, config_data: ConfigData, entry_id: str | None = None
    ):
        try:
            self._hass = hass
            self._config_data = config_data
            self._entry_id = entry_id

            self._status = None
            self._session = None

            self._base_url = None
            self._pending_payloads = []
            self._ws = None
            self._api_data = {}
            self._data = {
                WS_EXPORT_KEY: {},
                WS_INTERFACES_KEY: {},
            }
            self._triggered_sensors = {}
            self._remove_async_track_time = None

            self._local_async_dispatcher_send = None

            self._messages_handler: dict = self._get_ws_handlers()

            self._can_log_messages: bool = False
            self._previous_message = None

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {DEFAULT_NAME} WS, error: {ex}, line: {line_number}"
            )

    @property
    def data(self) -> dict:
        return self._data

    @property
    def status(self) -> str | None:
        status = self._status

        return status

    @property
    def _is_home_assistant(self):
        return self._hass is not None

    @property
    def _has_running_loop(self):
        return self._hass.loop is not None and not self._hass.loop.is_closed()

    @property
    def _api_session_id(self):
        api_session_id = self._api_data.get(API_DATA_SESSION_ID)

        return api_session_id

    @property
    def _api_cookies(self):
        api_cookies = self._api_data.get(API_DATA_COOKIES)

        return api_cookies

    def update_api_data(self, api_data: dict, can_log_messages: bool):
        self._api_data = api_data
        self._can_log_messages = can_log_messages

    async def initialize(self):
        """Connect and listen until the connection drops.

        Returns once the connection is gone, the caller is responsible for
        deciding whether to reconnect.
        """
        # The subscription is rejected without a session id and the router then
        # stays silent, which used to look like a healthy but idle connection
        if self._api_session_id is None:
            _LOGGER.warning(
                "Cannot connect WS, Reason: API did not provide a session id yet"
            )

            self._set_status(ConnectivityStatus.NotConnected)

            return

        try:
            _LOGGER.debug("Initializing")

            await self._initialize_session()

            # Bounded, so that a router that accepts the TCP connection but never
            # completes the upgrade cannot block the supervisor indefinitely
            ws = await asyncio.wait_for(
                self._session.ws_connect(
                    self._config_data.ws_url,
                    ssl=False,
                    autoclose=True,
                    max_msg_size=WS_MAX_MSG_SIZE,
                    timeout=WS_CLOSE_TIMEOUT,
                    receive_timeout=WS_RECEIVE_TIMEOUT,
                    compress=WS_COMPRESSION_DEFLATE,
                ),
                WS_CONNECT_TIMEOUT,
            )

            try:
                self._ws = ws

                await self._listen()

            finally:
                if not ws.closed:
                    await ws.close()

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            if self.status == ConnectivityStatus.Connected:
                _LOGGER.info(
                    f"WS got disconnected will try to recover, Error: {ex}, Line: {line_number}"
                )

                self._set_status(ConnectivityStatus.NotConnected)

            else:
                _LOGGER.warning(
                    f"Failed to connect WS, Error: {ex}, Line: {line_number}"
                )

                self._set_status(ConnectivityStatus.Failed)

        finally:
            self._ws = None

            await self._close_session()

    async def terminate(self):
        if self._remove_async_track_time is not None:
            self._remove_async_track_time()
            self._remove_async_track_time = None

        if self._ws is not None:
            try:
                await self._ws.close()

                await asyncio.sleep(DISCONNECT_INTERVAL)

            except Exception as ex:
                _LOGGER.debug(f"Failed to close WS gracefully, Error: {ex}")

        self._set_status(ConnectivityStatus.Disconnected)
        self._ws = None

        await self._close_session()

    async def async_disconnect(self):
        """Close the socket without waiting for the listener to notice.

        This releases a caller blocked in `initialize`, so that the connection
        supervisor can come back round its loop and rebuild the whole session.
        The status is deliberately left alone - the listen loop sets it as its
        iteration ends, which keeps one place responsible for it.
        """
        ws = self._ws

        if ws is None or ws.closed:
            return

        _LOGGER.debug("Closing WS to let the connection be rebuilt")

        try:
            await ws.close()

        except Exception as ex:
            _LOGGER.debug(f"Failed to close WS, Error: {ex}")

    async def _close_session(self):
        """Release the client session, a new one is created per connection."""
        session = self._session
        self._session = None

        if session is None or session.closed:
            return

        try:
            await session.close()

        except Exception as ex:
            _LOGGER.debug(f"Failed to close WS session, Error: {ex}")

    async def _initialize_session(self):
        try:
            await self._close_session()

            if self._is_home_assistant:
                self._session = async_create_clientsession(hass=self._hass)

            else:
                self._session = ClientSession()

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.warning(
                f"Failed to initialize session, Error: {str(ex)}, Line: {line_number}"
            )

            self._set_status(ConnectivityStatus.Failed)

    async def send_heartbeat(self):
        if self._session is None or self._session.closed:
            self._set_status(ConnectivityStatus.NotConnected)

        if self.status == ConnectivityStatus.Connected:
            content = {"CLIENT_PING": "", "SESSION_ID": self._api_session_id}

            content_str = json.dumps(content)
            data = f"{len(content_str)}\n{content_str}"
            data_for_log = data.replace("\n", "")

            _LOGGER.debug(f"Keep alive data to be sent: {data_for_log}")

            try:
                await self._ws.send_str(data)

            except ConnectionResetError as crex:
                _LOGGER.debug(
                    f"Gracefully failed to send heartbeat - Restarting connection, Error: {crex}"
                )
                self._set_status(ConnectivityStatus.NotConnected)

            except Exception as ex:
                _LOGGER.error(f"Failed to send heartbeat, Error: {ex}")

    async def _listen(self):
        _LOGGER.info("Starting to listen connected")

        subscription_data = self._get_subscription_data()
        await self._ws.send_str(subscription_data)

        self._set_status(ConnectivityStatus.Connected)

        async for msg in self._ws:
            is_ha_running = self._hass.is_running
            is_connected = self.status == ConnectivityStatus.Connected
            is_closing_type = msg.type in WS_CLOSING_MESSAGE
            is_error = msg.type == aiohttp.WSMsgType.ERROR
            can_try_parse_message = msg.type == aiohttp.WSMsgType.TEXT
            is_closing_data = (
                False if is_closing_type or is_error else msg.data == "close"
            )
            session_is_closed = self._session is None or self._session.closed

            not_connected = True in [
                is_closing_type,
                is_error,
                is_closing_data,
                session_is_closed,
                not is_connected,
            ]

            if not is_ha_running:
                self._set_status(ConnectivityStatus.Disconnected)
                return

            if not_connected:
                _LOGGER.warning(
                    f"WS stopped listening, "
                    f"Message: {str(msg)}, "
                    f"Exception: {self._ws.exception()}"
                )

                self._set_status(ConnectivityStatus.NotConnected)
                return

            elif can_try_parse_message:
                if self._can_log_messages:
                    _LOGGER.debug(f"Message received: {str(msg)}")

                self.data[API_DATA_LAST_UPDATE] = datetime.now().isoformat()

                await self._parse_message(msg.data)

    async def _parse_message(self, message: str):
        try:
            self._increase_counter(WS_RECEIVED_MESSAGES)

            if self._previous_message is not None:
                message = self._get_corrected_message(message)

            if message is not None:
                message_json = re.sub(BEGINS_WITH_SIX_DIGITS, EMPTY_STRING, message)

                if len(message_json.strip()) > 0:
                    payload_json = json.loads(message_json)

                    await self._message_handler(payload_json)

                    self._async_dispatcher_send(SIGNAL_WS_DATA_CHANGED)
            else:
                self._increase_counter(WS_IGNORED_MESSAGES)

        except ValueError:
            self._increase_counter(WS_IGNORED_MESSAGES)

            previous_messages = re.findall(BEGINS_WITH_SIX_DIGITS, message)

            if previous_messages is None or len(previous_messages) == 0:
                _LOGGER.warning("Failed to store partial message for later processing")

            else:
                length = int(previous_messages[0])

                self._previous_message = {"Length": length, "Content": message}

                _LOGGER.debug("Store partial message for later processing")

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.warning(
                f"Parse message failed, Data: {message}, Error: {ex}, Line: {line_number}"
            )

    def _get_corrected_message(self, message):
        original_message = message
        previous_message = self._previous_message.get("Content")
        previous_message_length = self._previous_message.get("Length")

        self._previous_message = None

        message = f"{previous_message}{message}"
        new_message_length = len(message) - len(str(previous_message_length)) - 1

        if new_message_length > previous_message_length:
            if self._can_log_messages:
                _LOGGER.debug(
                    f"Ignored partial message, "
                    f"Expected {previous_message_length} chars, "
                    f"Provided {new_message_length}, "
                    f"Content: {message}"
                )

            else:
                _LOGGER.debug(
                    f"Ignored partial message, "
                    f"Expected {previous_message_length} chars, "
                    f"Provided {new_message_length}"
                )

            message = original_message

        else:
            self._decrease_counter(WS_IGNORED_MESSAGES)
            _LOGGER.debug("Partial message corrected")

        return message

    def _get_subscription_data(self):
        topics = self._messages_handler.keys()

        topics_to_subscribe = [{WS_TOPIC_NAME: topic} for topic in topics]
        topics_to_unsubscribe = []

        data = {
            WS_TOPIC_SUBSCRIBE: topics_to_subscribe,
            WS_TOPIC_UNSUBSCRIBE: topics_to_unsubscribe,
            WS_SESSION_ID: self._api_session_id,
        }

        content = json.dumps(data, separators=(STRING_COMMA, STRING_COLON))
        content_length = len(content)
        data = f"{content_length}\n{content}"
        data_for_log = data.replace("\n", "")

        _LOGGER.debug(f"Subscription data to be sent: {data_for_log}")

        return data

    def _set_status(self, status: ConnectivityStatus):
        if status != self._status:
            log_level = ConnectivityStatus.get_log_level(status)

            _LOGGER.log(
                log_level,
                f"Status changed from '{self._status}' to '{status}'",
            )

            self._status = status

            self._async_dispatcher_send(
                SIGNAL_WS_STATUS,
                status,
            )

    def set_local_async_dispatcher_send(self, callback):
        self._local_async_dispatcher_send = callback

    def _async_dispatcher_send(self, signal: str, *args: Any) -> None:
        if self._hass is None:
            self._local_async_dispatcher_send(signal, self._entry_id, *args)

        else:
            dispatcher_send(self._hass, signal, self._entry_id, *args)

    def _increase_counter(self, key):
        counter = self.data.get(key, 0)

        self.data[key] = counter + 1

    def _decrease_counter(self, key):
        counter = self.data.get(key, 0)

        self.data[key] = counter - 1

    def _get_ws_handlers(self) -> dict:
        # The keys double as the list of topics that gets subscribed to
        ws_handlers = {
            WS_EXPORT_KEY: self._handle_export,
            WS_INTERFACES_KEY: self._handle_interfaces,
            WS_SYSTEM_STATS_KEY: self._handle_system_stats,
            WS_DISCOVER_KEY: self._handle_discover,
            WS_CONFIG_CHANGE_KEY: self._handle_config_change,
        }

        return ws_handlers

    async def _message_handler(self, payload=None):
        try:
            if payload is not None:
                for key in payload:
                    data = payload.get(key)
                    handler = self._messages_handler.get(key)

                    if handler is None:
                        _LOGGER.error(f"Handler not found for {key}")
                    else:
                        handler(data)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to handle WS message, Error: {ex}, Line: {line_number}"
            )

    def _handle_export(self, data):
        try:
            _LOGGER.debug(f"Handle {WS_EXPORT_KEY} data")

            if data is None or data == "":
                _LOGGER.debug(f"{WS_EXPORT_KEY} is empty")
                return

            for device_ip in data:
                device_data = data.get(device_ip)

                if device_data is not None:
                    traffic: dict = {}

                    for direction in TRAFFIC_DATA_DIRECTIONS:
                        for key in TRAFFIC_DATA_DEVICE_ITEMS:
                            stats_key = f"{direction}_{key}"
                            traffic[stats_key] = float(0)

                    for service in device_data:
                        service_data = device_data.get(service, {})
                        for item in service_data:
                            current_value = traffic.get(item, 0)
                            service_data_item_value = 0

                            if item in service_data and service_data[item] != "":
                                service_data_item_value = float(service_data[item])

                            traffic_value = current_value + service_data_item_value

                            traffic[item] = traffic_value

                    self.data[WS_EXPORT_KEY][device_ip] = traffic

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {WS_EXPORT_KEY}, Error: {ex}, Line: {line_number}"
            )

    def _handle_interfaces(self, data):
        try:
            _LOGGER.debug(f"Handle {WS_INTERFACES_KEY} data")

            if data is None or data == "":
                _LOGGER.debug(f"{WS_INTERFACES_KEY} is empty")
                return

            for name in data:
                interface_data = data.get(name)

                interface = {}

                for item in interface_data:
                    item_data = interface_data.get(item)

                    if ADDRESS_LIST == item:
                        interface[item] = item_data

                    elif INTERFACES_STATS == item:
                        interface[INTERFACE_DATA_MULTICAST] = float(
                            item_data.get(INTERFACE_DATA_MULTICAST)
                        )

                        for direction in TRAFFIC_DATA_DIRECTIONS:
                            for key in TRAFFIC_DATA_INTERFACE_ITEMS:
                                stats_key = f"{direction}_{key}"

                                interface[stats_key] = float(item_data.get(stats_key))

                    else:
                        if item in INTERFACES_MAIN_MAP:
                            interface[item] = item_data

                self.data[WS_INTERFACES_KEY][name] = interface

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {WS_INTERFACES_KEY}, Error: {ex}, Line: {line_number}"
            )

    def _handle_system_stats(self, data):
        try:
            _LOGGER.debug(f"Handle {WS_SYSTEM_STATS_KEY} data")

            if data is None or data == "":
                _LOGGER.debug(f"{WS_SYSTEM_STATS_KEY} is empty")
                return

            self.data[WS_SYSTEM_STATS_KEY] = data
        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {WS_SYSTEM_STATS_KEY}, Error: {ex}, Line: {line_number}"
            )

    def _handle_config_change(self, data):
        """Announce that the router's configuration was committed.

        Anything derived from the configuration - firewall rules, interface
        settings - is stale from this moment until it is read again, so this is
        what makes those entities update within a second of a change instead of
        waiting for the next scheduled poll.
        """
        try:
            if not isinstance(data, dict):
                return

            commit = data.get(CONFIG_CHANGE_COMMIT)

            _LOGGER.debug(f"Handle {WS_CONFIG_CHANGE_KEY} data, Commit: {commit}")

            if commit != CONFIG_CHANGE_COMMIT_ENDED:
                return

            self._async_dispatcher_send(SIGNAL_CONFIG_CHANGED)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {WS_CONFIG_CHANGE_KEY}, Error: {ex}, Line: {line_number}"
            )

    def _handle_discover(self, data):
        try:
            _LOGGER.debug(f"Handle {WS_DISCOVER_KEY} data")

            if data is None or data == "":
                _LOGGER.debug(f"{WS_DISCOVER_KEY} is empty")
                return

            devices_data = data.get(DEVICE_LIST, [])
            result = {}

            for device_data in devices_data:
                for key in DISCOVER_DEVICE_ITEMS:
                    device_data_item = device_data.get(key, {})

                    if key == ADDRESS_LIST:
                        discover_addresses = {}

                        for address in device_data_item:
                            hw_addr = address.get(ADDRESS_HW_ADDR)
                            ipv4 = address.get(ADDRESS_IPV4)

                            discover_addresses[hw_addr] = ipv4

                        result[key] = discover_addresses
                    else:
                        result[key] = device_data_item

            self.data[WS_DISCOVER_KEY] = result
        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to load {WS_DISCOVER_KEY}, Original Message: {data}, Error: {ex}, Line: {line_number}"
            )
