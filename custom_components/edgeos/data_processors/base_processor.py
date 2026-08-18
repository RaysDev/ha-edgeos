import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import slugify

from ..common.consts import (
    API_DATA_SYSTEM,
    DATA_SYSTEM_SYSTEM,
    DEFAULT_NAME,
    SYSTEM_DATA_HOSTNAME,
)
from ..common.enums import DeviceTypes
from ..models.config_data import ConfigData

_LOGGER = logging.getLogger(__name__)


class BaseProcessor:
    _api_data: dict | None = None
    _ws_data: dict | None = None
    _config_data: ConfigData | None = None
    _unique_messages: list[str] | None = None
    processor_type: DeviceTypes | None = None
    _hostname: str | None = None

    def __init__(self, config_data: ConfigData):
        self._config_data = config_data

        self._api_data = None
        self._ws_data = None
        self.processor_type = None
        self._hostname = None

        self._unique_messages = []

    def update(self, api_data: dict, ws_data: dict):
        self._api_data = api_data
        self._ws_data = ws_data

        self._process_api_data()
        self._process_ws_data()

    def update_ws_data(self, ws_data: dict):
        """Re-derive only what the statistics stream provides.

        The router's configuration is re-read when a poll falls due or a commit
        is announced, never by one of these messages, so deriving it again here
        - for every interface, every DHCP lease and every firewall rule, once or
        twice a second - could not produce a different answer.

        Only safe once `update` has run at least once, because the statistics
        are attached to the objects that pass builds.
        """
        self._ws_data = ws_data

        self._process_ws_data()

    @staticmethod
    def _normalize_id(value: str | None) -> str | None:
        """Normalize externally supplied identifiers to lowercase.

        The API/websocket data contains mixed-case MAC addresses and hostnames.
        Keep all internal lookups lowercase so "aa:bb" and "AA:BB" resolve to the
        same record.
        """
        if value is None:
            return None
        return value.lower()

    def _process_api_data(self):
        system_section = self._api_data.get(API_DATA_SYSTEM, {})
        system_details = system_section.get(DATA_SYSTEM_SYSTEM, {})

        hostname = system_details.get(SYSTEM_DATA_HOSTNAME)

        # Raised an AttributeError before any configuration had been read, which
        # aborted every processor rather than letting the caller notice that the
        # hostname is not known yet
        self._hostname = None if hostname is None else hostname.upper()

    def _process_ws_data(self):
        pass

    def _unique_log(self, log_level: int, message: str):
        if message not in self._unique_messages:
            self._unique_messages.append(message)

            _LOGGER.log(log_level, message)

    def get_device_info(self, item_id: str | None = None) -> DeviceInfo:
        device_name = self._get_device_info_name(item_id)

        unique_id = self._get_device_info_unique_id(item_id)

        device_info = DeviceInfo(
            identifiers={(DEFAULT_NAME, unique_id)},
            name=device_name,
            model=self.processor_type,
            manufacturer=DEFAULT_NAME,
            via_device=(DEFAULT_NAME, self._hostname),
        )

        return device_info

    def get_item_name(self, item_id: str | None = None) -> str | None:
        """What one item is called within the device that holds it.

        Used where a single device holds many entities that differ by item
        rather than by kind - a firewall rule-set holding its rules, or the
        shared device holding a monitoring toggle per EdgeOS device. `None`
        means the processor has no opinion and the name is built from the entity
        description, as it is for everything else.
        """
        return None

    def get_shared_device_info(self) -> DeviceInfo | None:
        """The one device that holds this type's item entities, if it has one."""
        return None

    @staticmethod
    def _prettify(text: str | None) -> str | None:
        """Make a configured name read as a name.

        Names are usually written `block-kid-tablet` or `Android-Nexus6`. One
        that already contains a space was written as prose and is left exactly
        as typed. Otherwise separators become spaces, and a word is capitalised
        only when it is entirely lower case - so `iPhone`, `NAS`, `DNS` and
        `IPv6` survive intact.
        """
        if text is None:
            return None

        stripped = text.strip()

        if not stripped:
            return None

        if " " in stripped:
            return stripped

        words = stripped.replace("-", " ").replace("_", " ").split()

        if not words:
            return None

        return " ".join(
            word if any(letter.isupper() for letter in word) else word.capitalize()
            for word in words
        )

    def _get_device_info_name(self, item_id: str | None = None):
        parts = [self._hostname, self.processor_type, item_id]

        relevant_parts = [part for part in parts if part is not None]

        name = " ".join(relevant_parts)

        return name

    def _get_device_info_unique_id(self, item_id: str | None = None):
        identifier = self._get_device_info_name(item_id)

        unique_id = slugify(identifier)

        return unique_id
