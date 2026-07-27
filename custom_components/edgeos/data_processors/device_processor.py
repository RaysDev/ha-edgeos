import logging
import sys

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import slugify

from ..common.consts import (
    API_DATA_DHCP_LEASES,
    API_DATA_SYSTEM,
    DATA_SYSTEM_SERVICE,
    DATA_SYSTEM_SERVICE_DHCP_SERVER,
    DEFAULT_NAME,
    DEVICE_DATA_MAC,
    DEVICE_MONITORING_NAME,
    DHCP_SERVER_IP_ADDRESS,
    DHCP_SERVER_LEASES,
    DHCP_SERVER_LEASES_CLIENT_HOSTNAME,
    DHCP_SERVER_MAC_ADDRESS,
    DHCP_SERVER_SHARED_NETWORK_NAME,
    DHCP_SERVER_STATIC_MAPPING,
    DHCP_SERVER_SUBNET,
    SYSTEM_DATA_DOMAIN_NAME,
    TRAFFIC_DATA_DEVICE_ITEMS,
    WS_EXPORT_KEY,
)
from ..common.enums import DeviceTypes
from ..models.config_data import ConfigData
from ..models.edge_os_device_data import EdgeOSDeviceData
from .base_processor import BaseProcessor

_LOGGER = logging.getLogger(__name__)


class DeviceProcessor(BaseProcessor):
    _devices: dict[str, EdgeOSDeviceData]
    _devices_ip_mapping: dict[str, str]

    def __init__(self, config_data: ConfigData):
        super().__init__(config_data)

        self.processor_type = DeviceTypes.DEVICE

        self._devices = {}
        self._devices_ip_mapping = {}
        self._leased_devices = {}

    def get_devices(self) -> list[str]:
        return list(self._devices.keys())

    def get_all(self) -> list[dict]:
        items = [self._devices[item_key].to_dict() for item_key in self._devices]

        return items

    def get_device(self, identifiers: set[tuple[str, str]]) -> dict | None:
        device: dict | None = None
        device_identifier = list(identifiers)[0][1]

        for device_mac in self._devices:
            unique_id = self._get_device_info_unique_id(device_mac)

            if unique_id == device_identifier:
                device = self._devices[device_mac].to_dict()

        return device

    def get_data(self, device_mac: str) -> EdgeOSDeviceData:
        interface_data = self._devices.get(device_mac)

        return interface_data

    def get_device_info(self, item_id: str | None = None) -> DeviceInfo:
        device = self.get_data(item_id)
        device_name = self._get_device_info_name(device.hostname)

        unique_id = self._get_device_info_unique_id(device.hostname)

        device_info = DeviceInfo(
            identifiers={(DEFAULT_NAME, unique_id)},
            name=device_name,
            model=self.processor_type,
            manufacturer=DEFAULT_NAME,
            via_device=(DEFAULT_NAME, self._hostname),
        )

        return device_info

    def get_shared_device_info(self) -> DeviceInfo:
        """The one device holding a monitoring toggle per EdgeOS device.

        Without it every device on the network needs a device of its own just to
        carry that toggle, which is most of them and none of them useful. A
        device now only exists once its toggle is on, because Home Assistant
        creates a device only when an entity points at it.
        """
        identifier = " ".join(
            part
            for part in [self._hostname, str(DeviceTypes.DEVICE_LIST)]
            if part is not None
        )
        name = " ".join(
            part
            for part in [self._hostname, DEVICE_MONITORING_NAME]
            if part is not None
        )

        return DeviceInfo(
            identifiers={(DEFAULT_NAME, slugify(identifier))},
            name=name,
            model=DeviceTypes.DEVICE_LIST,
            manufacturer=DEFAULT_NAME,
            via_device=(DEFAULT_NAME, self._hostname),
        )

    def get_item_name(self, item_id: str | None = None) -> str | None:
        """What one device's toggle is called on the shared device."""
        device = self._devices.get(item_id)

        if device is None:
            return None if item_id is None else str(item_id)

        return self._prettify(device.hostname) or device.hostname or str(item_id)

    def get_leased_devices(self) -> dict:
        return self._leased_devices

    def _process_api_data(self):
        super()._process_api_data()

        try:
            system_section = self._api_data.get(API_DATA_SYSTEM, {})
            service = system_section.get(DATA_SYSTEM_SERVICE, {})

            dhcp_server = service.get(DATA_SYSTEM_SERVICE_DHCP_SERVER, {})
            shared_network_names = dhcp_server.get(DHCP_SERVER_SHARED_NETWORK_NAME, {})

            for shared_network_name in shared_network_names:
                shared_network_name_data = shared_network_names.get(
                    shared_network_name, {}
                )
                subnets = shared_network_name_data.get(DHCP_SERVER_SUBNET, {})

                for subnet in subnets:
                    subnet_data = subnets.get(subnet, {})

                    domain_name = subnet_data.get(SYSTEM_DATA_DOMAIN_NAME)
                    static_mappings = subnet_data.get(DHCP_SERVER_STATIC_MAPPING, {})

                    for hostname in static_mappings:
                        static_mapping_data = static_mappings.get(hostname, {})

                        self._set_device(
                            hostname, domain_name, static_mapping_data, False
                        )

            # Once per pass, after every static mapping is known. Nested in the
            # loop above it ran once per shared network, and not at all on a
            # router with none configured - where `Unknown Devices` then always
            # reported zero.
            self._update_leased_devices()

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract Devices data, Error: {ex}, Line: {line_number}"
            )

    def _process_ws_data(self):
        try:
            device_data = self._ws_data.get(WS_EXPORT_KEY, {})

            for device_ip in device_data:
                device_item = self._get_device_by_ip(device_ip)
                stats = device_data.get(device_ip)

                if device_item is not None:
                    self._update_device_stats(device_item, stats)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract WS data, Error: {ex}, Line: {line_number}"
            )

    def _update_leased_devices(self):
        try:
            data_leases = self._api_data.get(API_DATA_DHCP_LEASES, {})
            data_server_leases = data_leases.get(DHCP_SERVER_LEASES, {})

            for subnet in data_server_leases:
                subnet_data = data_server_leases.get(subnet, {})

                for ip in subnet_data:
                    device_data = subnet_data.get(ip)

                    hostname = device_data.get(DHCP_SERVER_LEASES_CLIENT_HOSTNAME)

                    static_mapping_data = {
                        DHCP_SERVER_IP_ADDRESS: ip,
                        DHCP_SERVER_MAC_ADDRESS: device_data.get(DEVICE_DATA_MAC),
                    }

                    self._set_device(hostname, None, static_mapping_data, True)

            self._leased_devices.clear()

            for device_mac in self._devices:
                device = self._devices.get(device_mac)
                if device.is_leased:
                    device_name = device.mac

                    if device.hostname not in ["", "?"]:
                        device_name = f"{device.mac} ({device.hostname})"

                    self._leased_devices[device.ip] = device_name

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to extract Unknown Devices data, Error: {ex}, Line: {line_number}"
            )

    def _set_device(
        self,
        hostname: str,
        domain_name: str | None,
        static_mapping_data: dict,
        is_leased: bool,
    ):
        ip_address = static_mapping_data.get(DHCP_SERVER_IP_ADDRESS)
        mac_address = static_mapping_data.get(DHCP_SERVER_MAC_ADDRESS)

        existing_device_data = self._devices.get(mac_address)

        if existing_device_data is None:
            device_data = EdgeOSDeviceData(
                hostname, ip_address, mac_address, domain_name, is_leased
            )

        else:
            device_data = existing_device_data

            # The address is what the traffic analysis stream is matched on. It
            # used to be kept at whatever it was when the device was first seen,
            # so a device that changed address stopped being matched at all -
            # its traffic sensors froze and its tracker reported away for good.
            if ip_address is not None and ip_address != device_data.ip:
                self._devices_ip_mapping.pop(device_data.ip, None)

                device_data.ip = ip_address

            # A static mapping means the device is known, whichever order it was
            # read in. Never the other way round: a lease seen after the mapping
            # would otherwise hide the device from discovery.
            if not is_leased:
                device_data.is_leased = False

            # `hostname` is deliberately left alone. `get_device_info` builds the
            # device identifier from it, so changing it here would orphan the
            # device already registered in Home Assistant.

        self._devices[device_data.unique_id] = device_data
        self._devices_ip_mapping[device_data.ip] = device_data.unique_id

    def _get_device(self, unique_id: str) -> EdgeOSDeviceData | None:
        device = self._devices.get(unique_id)

        return device

    def _get_device_by_ip(self, ip: str) -> EdgeOSDeviceData | None:
        unique_id = self._devices_ip_mapping.get(ip)

        device = self._get_device(unique_id)

        return device

    @staticmethod
    def _update_device_stats(device_data: EdgeOSDeviceData, stats: dict):
        try:
            if not device_data.is_leased:
                directions = [device_data.received, device_data.sent]

                for direction in directions:
                    stat_data = {}
                    for stat_key in TRAFFIC_DATA_DEVICE_ITEMS:
                        key = f"{direction.direction}_{stat_key}"
                        stat_data_item = TRAFFIC_DATA_DEVICE_ITEMS.get(stat_key)

                        stat_data[stat_data_item] = stats.get(key)

                    direction.update(stat_data)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                f"Failed to update device statistics for {device_data.hostname}, "
                f"Error: {ex}, "
                f"Line: {line_number}"
            )
