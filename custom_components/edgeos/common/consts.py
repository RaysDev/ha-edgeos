"""
Support for Constants.
"""
from datetime import timedelta

import aiohttp

from homeassistant.const import UnitOfDataRate, UnitOfInformation

from .enums import (
    DeviceTypes,
    DynamicInterfaceTypes,
    EntityValidation,
    InterfaceTypes,
    UnitOfEdgeOS,
)

ENTITY_CONFIG_ENTRY_ID = "entry_id"

HA_NAME = "homeassistant"

DOMAIN = "edgeos"
DEFAULT_NAME = "EdgeOS"
MANUFACTURER = "Ubiquiti"

STORAGE_DATA_KEY = "key"

SIGNAL_INTERFACE_ADDED = f"{DOMAIN}_INTERFACE_ADDED_SIGNAL"
SIGNAL_DEVICE_ADDED = f"{DOMAIN}_DEVICE_ADDED_SIGNAL"
SIGNAL_SYSTEM_ADDED = f"{DOMAIN}_SYSTEM_ADDED_SIGNAL"
SIGNAL_FIREWALL_RULE_ADDED = f"{DOMAIN}_FIREWALL_RULE_ADDED_SIGNAL"
SIGNAL_DATA_CHANGED = f"{DOMAIN}_DATA_CHANGED_SIGNAL"
SIGNAL_CONFIG_CHANGED = f"{DOMAIN}_CONFIG_CHANGED_SIGNAL"

# Raised for every message the statistics stream delivers, several times a
# second. Kept apart from SIGNAL_DATA_CHANGED so that the configuration, which
# those messages cannot change, is not re-derived each time.
SIGNAL_WS_DATA_CHANGED = f"{DOMAIN}_WS_DATA_CHANGED_SIGNAL"

SIGNAL_WS_STATUS = f"{DOMAIN}_WS_STATUS_SIGNAL"
SIGNAL_API_STATUS = f"{DOMAIN}_API_STATUS_SIGNAL"

ADD_COMPONENT_SIGNALS = [
    SIGNAL_INTERFACE_ADDED,
    SIGNAL_DEVICE_ADDED,
    SIGNAL_SYSTEM_ADDED,
    SIGNAL_FIREWALL_RULE_ADDED,
]

MAXIMUM_RECONNECT = 3
CONFIGURATION_FILE = f"{DOMAIN}.config.json"

INVALID_TOKEN_SECTION = (
    "https://github.com/blchinezu/ha-edgeos#encryption-key-got-corrupted"
)

API_URL_TEMPLATE = "https://{}"
WEBSOCKET_URL_TEMPLATE = "wss://{}/ws/stats"

COOKIE_PHPSESSID = "PHPSESSID"
COOKIE_BEAKER_SESSION_ID = "beaker.session.id"
COOKIE_CSRF_TOKEN = "X-CSRF-TOKEN"

HEADER_CSRF_TOKEN = "X-Csrf-token"
EMPTY_STRING = ""
CONF_TITLE = "title"

ATTR_ATTRIBUTES = "attributes"
ATTR_ACTIONS = "actions"
ATTR_IS_ON = "is_on"
ATTR_LAST_ACTIVITY = "last activity"
ATTR_HOSTNAME = "hostname"

ATTR_INSTALLED_VERSION = "installed_version"
ATTR_LATEST_VERSION = "latest_version"
ATTR_RELEASE_URL = "release_url"
ATTR_TITLE = "title"

# Entities earlier versions created that no longer exist, as (domain, unique id).
# Without this they linger in the registry as permanently unavailable, which is
# exactly the sort of leftover the rest of this integration now cleans up.
RETIRED_ENTITIES = [
    # Replaced by an `update` entity, which is what Home Assistant has for this
    ("binary_sensor", "edgeos_binary_sensor_firmware"),
]

ACTION_ENTITY_TURN_ON = "turn_on"
ACTION_ENTITY_TURN_OFF = "turn_off"
ACTION_ENTITY_SET_NATIVE_VALUE = "set_native_value"
ACTION_ENTITY_SELECT_OPTION = "select_option"

WS_MAX_MSG_SIZE = 0
DISCONNECT_INTERVAL = 5

WS_COMPRESSION_DEFLATE = 15

# Time allowed for the WebSocket close handshake, in seconds.
WS_CLOSE_TIMEOUT = 10

# Time allowed to establish the WebSocket, in seconds.
WS_CONNECT_TIMEOUT = 30

# The router streams `system-stats` and `interfaces` every few seconds, so a
# silent connection means the peer is gone. Without this, a router that
# disappears without closing the TCP connection (a reboot, a network blip)
# leaves the listener blocked forever and the integration believes it is still
# connected.
WS_RECEIVE_TIMEOUT = 60

DEFAULT_UPDATE_API_INTERVAL = timedelta(minutes=1)
DEFAULT_UPDATE_ENTITIES_INTERVAL = timedelta(seconds=1)
DEFAULT_CONSIDER_AWAY_INTERVAL = timedelta(minutes=3)
HEARTBEAT_INTERVAL = timedelta(seconds=25)

# The entities interval becomes the coordinator's `update_interval`, and a
# `timedelta(0)` reschedules with no delay at all - a tight loop that pins a
# core and can only be undone by editing the stored configuration by hand. The
# minimum is applied when the value is read as well as in the entity, because a
# zero may already be stored from before it existed.
MINIMUM_UPDATE_INTERVAL = 1

# Reconnection backoff, doubling from MIN up to MAX for as long as the router
# stays unreachable. The connection supervisor never gives up.
RECONNECT_INTERVAL_MIN = timedelta(seconds=5)
RECONNECT_INTERVAL_MAX = timedelta(minutes=5)

# Bad credentials are not going to fix themselves within seconds, but they can
# be fixed on the router, so retry slowly instead of stopping altogether.
RECONNECT_INTERVAL_INVALID_CREDENTIALS = timedelta(minutes=5)

# A WebSocket session that lasted at least this long counts as having worked,
# so the next disconnect reconnects immediately rather than backing off.
STABLE_CONNECTION_THRESHOLD = timedelta(seconds=30)

# How long the coordinator tolerates not being connected before it says so.
CONNECTION_WATCHDOG_INTERVAL = timedelta(minutes=2)

# Comfortably above `RECONNECT_INTERVAL_MAX`, so this only triggers when the
# supervisor is genuinely stuck rather than backing off.
SUPERVISOR_STALL_TIMEOUT = timedelta(minutes=10)

STORAGE_DATA_MONITORED_INTERFACES = "monitored-interfaces"
STORAGE_DATA_MONITORED_DEVICES = "monitored-devices"
STORAGE_DATA_LOG_INCOMING_MESSAGES = "log-incoming-messages"
STORAGE_DATA_CONSIDER_AWAY_INTERVAL = "consider-away-interval"
STORAGE_DATA_UPDATE_ENTITIES_INTERVAL = "update-entities-interval"
STORAGE_DATA_UPDATE_API_INTERVAL = "update-api-interval"
STORAGE_DATA_UNIT = "unit"

API_DATA_LAST_UPDATE = "lastUpdate"

API_DATA_PRODUCT = "product"
API_DATA_SYSTEM = "system"
API_DATA_INTERFACES = "interfaces"
API_DATA_SESSION_ID = "session-id"
API_DATA_COOKIES = "cookies"

API_DATA_SAVE = "SAVE"

API_GET = "get"
API_SET = "set"
API_DELETE = "delete"
API_DATA = "data"

API_URL_PARAMETER_BASE_URL = "base_url"
API_URL_PARAMETER_TIMESTAMP = "timestamp"
API_URL_PARAMETER_ACTION = "action"
API_URL_PARAMETER_SUBSET = "subset"

API_URL_DATA = "{base_url}/api/edge/{action}.json"
API_URL_DATA_SUBSET = f"{API_URL_DATA}?data={{subset}}"

TRUE_STR = "true"
FALSE_STR = "false"

INTERFACES_STATS = "stats"

# CHANGE TO API DATA
API_DATA_DHCP_STATS = "dhcp_stats"
API_DATA_SYS_INFO = "sys_info"
API_DATA_DHCP_LEASES = "dhcp-leases"

DATA_SYSTEM_SYSTEM = "system"
DATA_SYSTEM_SERVICE = "service"
DATA_SYSTEM_SERVICE_DHCP_SERVER = "dhcp-server"

DHCP_SERVER_LEASES = "dhcp-server-leases"
DHCP_SERVER_STATS = "dhcp-server-stats"
DHCP_SERVER_LEASED = "leased"
DHCP_SERVER_LEASES_CLIENT_HOSTNAME = "client-hostname"
DHCP_SERVER_SHARED_NETWORK_NAME = "shared-network-name"
DHCP_SERVER_SUBNET = "subnet"
DHCP_SERVER_STATIC_MAPPING = "static-mapping"
DHCP_SERVER_IP_ADDRESS = "ip-address"
DHCP_SERVER_MAC_ADDRESS = "mac-address"

WS_INTERFACES_KEY = "interfaces"
WS_SYSTEM_STATS_KEY = "system-stats"
WS_EXPORT_KEY = "export"
WS_DISCOVER_KEY = "discover"
WS_CONFIG_CHANGE_KEY = "config-change"

# The router announces every configuration commit, from any source - this
# integration, the web UI, or the CLI.
CONFIG_CHANGE_COMMIT = "commit"
CONFIG_CHANGE_COMMIT_ENDED = "ended"

# How long a state written by Home Assistant is trusted over the value read from
# the router's configuration, so that a switch does not bounce back to its
# previous position between the write and the configuration being re-read.
PENDING_STATE_TIMEOUT = timedelta(seconds=15)

# How long an item has to stay absent from the router's configuration before its
# device is deleted. Deleting a device destroys the user's customisations - the
# entity names, areas and icons they set - so a single odd configuration read
# must not be enough to trigger it.
REMOVED_ITEM_GRACE_PERIOD = timedelta(minutes=2)

WS_RECEIVED_MESSAGES = "received-messages"
WS_IGNORED_MESSAGES = "ignored-messages"

UPDATE_DATE_ENDPOINTS = [
    API_DATA_SYS_INFO,
    API_DATA_DHCP_STATS,
    API_DATA_DHCP_LEASES,
]

DISCOVER_DATA_FW_VERSION = "fwversion"
DISCOVER_DATA_PRODUCT = "product"

SYSTEM_STATS_DATA_UPTIME = "uptime"
SYSTEM_STATS_DATA_CPU = "cpu"
SYSTEM_STATS_DATA_MEM = "mem"

DEVICE_LIST = "devices"
ADDRESS_LIST = "addresses"
ADDRESS_IPV4 = "ipv4"
ADDRESS_HW_ADDR = "hwaddr"

RESPONSE_SUCCESS_KEY = "success"
RESPONSE_ERROR_KEY = "error"
RESPONSE_OUTPUT = "output"
RESPONSE_FAILURE_CODE = "0"

WS_TOPIC_NAME = "name"
WS_TOPIC_UNSUBSCRIBE = "UNSUBSCRIBE"
WS_TOPIC_SUBSCRIBE = "SUBSCRIBE"
WS_SESSION_ID = "SESSION_ID"

BEGINS_WITH_SIX_DIGITS = "^([0-9]{1,6})"

STRING_DASH = "-"
STRING_UNDERSCORE = "_"
STRING_COMMA = ","
STRING_COLON = ":"

SYSTEM_DATA_HOSTNAME = "host-name"
SYSTEM_DATA_DOMAIN_NAME = "domain-name"
SYSTEM_DATA_NTP = "ntp"
SYSTEM_DATA_NTP_SERVER = "server"
SYSTEM_DATA_OFFLOAD = "offload"
SYSTEM_DATA_OFFLOAD_HW_NAT = "hwnat"
SYSTEM_DATA_OFFLOAD_IPSEC = "ipsec"
SYSTEM_DATA_TRAFFIC_ANALYSIS = "traffic-analysis"
SYSTEM_DATA_TRAFFIC_ANALYSIS_DPI = "dpi"
SYSTEM_DATA_TRAFFIC_ANALYSIS_EXPORT = "export"
SYSTEM_DATA_TIME_ZONE = "time-zone"
SYSTEM_DATA_LOGIN = "login"
SYSTEM_DATA_LOGIN_USER = "user"
SYSTEM_DATA_LOGIN_USER_LEVEL = "level"

USER_LEVEL_ADMIN = "admin"

SYSTEM_INFO_DATA_FW_LATEST = "fw-latest"
SYSTEM_INFO_DATA_FW_LATEST_STATE = "state"
SYSTEM_INFO_DATA_FW_LATEST_VERSION = "version"
SYSTEM_INFO_DATA_FW_LATEST_URL = "url"

FW_LATEST_STATE_CAN_UPGRADE = "can-upgrade"

SYSTEM_INFO_DATA_SW_VER = "sw_ver"

SYSTEM_DATA_ENABLE = "enable"
SYSTEM_DATA_DISABLE = "disable"

INTERFACE_DATA_NAME = "name"
INTERFACE_DATA_DESCRIPTION = "description"
INTERFACE_DATA_TYPE = "type"
INTERFACE_DATA_DUPLEX = "duplex"
INTERFACE_DATA_SPEED = "speed"
INTERFACE_DATA_BRIDGE_GROUP = "bridge-group"
INTERFACE_DATA_ADDRESS = "address"
INTERFACE_DATA_AGING = "aging"
INTERFACE_DATA_BRIDGED_CONNTRACK = "bridged-conntrack"
INTERFACE_DATA_HELLO_TIME = "hello-time"
INTERFACE_DATA_MAX_AGE = "max-age"
INTERFACE_DATA_PRIORITY = "priority"
INTERFACE_DATA_PROMISCUOUS = "promiscuous"
INTERFACE_DATA_STP = "stp"
INTERFACE_DATA_RECEIVED = "received"
INTERFACE_DATA_SENT = "sent"
INTERFACE_DATA_MULTICAST = "multicast"
INTERFACE_DATA_UP = "up"
INTERFACE_DATA_LINK_UP = "l1up"
INTERFACE_DATA_MAC = "mac"
INTERFACE_DATA_IS_SUPPORTED = "is_supported"

DATA_SYSTEM_FIREWALL = "firewall"

# A rule-set device reads `{HOST} Firewall {RULESET}`. The identifier is built
# from the device model instead, so that renaming a rule-set on the router - or
# changing how the name reads here - cannot orphan a device.
FIREWALL_DEVICE_NAME = "Firewall"

# The shared device reads `{HOST} Device Monitoring`. As with the firewall, its
# identifier comes from the model instead, so the wording here is free to change.
DEVICE_MONITORING_NAME = "Device Monitoring"

# Keys of a rule-set / rule within the `firewall` section of the configuration
FIREWALL_DATA_RULE = "rule"
FIREWALL_DATA_ACTION = "action"
FIREWALL_DATA_DESCRIPTION = "description"
FIREWALL_DATA_PROTOCOL = "protocol"
FIREWALL_DATA_LOG = "log"
FIREWALL_DATA_STATE = "state"
FIREWALL_DATA_SOURCE = "source"
FIREWALL_DATA_DESTINATION = "destination"
FIREWALL_DATA_DEFAULT_ACTION = "default-action"

# Keys of the dictionary representation of a firewall rule
FIREWALL_RULE_DATA_RULESET = "ruleset"
FIREWALL_RULE_DATA_RULESET_DESCRIPTION = "ruleset_description"
FIREWALL_RULE_DATA_RULESET_DEFAULT_ACTION = "ruleset_default_action"
FIREWALL_RULE_DATA_NUMBER = "number"
FIREWALL_RULE_DATA_IS_IPV6 = "ipv6"
FIREWALL_RULE_DATA_DESCRIPTION = "description"
FIREWALL_RULE_DATA_ACTION = "action"
FIREWALL_RULE_DATA_PROTOCOL = "protocol"
FIREWALL_RULE_DATA_LOG = "log"
FIREWALL_RULE_DATA_STATE = "state"
FIREWALL_RULE_DATA_SOURCE = "source"
FIREWALL_RULE_DATA_DESTINATION = "destination"
FIREWALL_RULE_DATA_IS_ENABLED = "is_enabled"

FIREWALL_RULE_ID_SEPARATOR = ":"
FIREWALL_RULE_ID_IPV6_PREFIX = "IPv6"

DEVICE_DATA_NAME = "hostname"
DEVICE_DATA_DOMAIN = "domain"
DEVICE_DATA_IP = "ip"
DEVICE_DATA_MAC = "mac"
DEVICE_DATA_RECEIVED = "received"
DEVICE_DATA_SENT = "sent"

TRAFFIC_DATA_DIRECTION = "direction"
TRAFFIC_DATA_RATE = "rate"
TRAFFIC_DATA_TOTAL = "total"
TRAFFIC_DATA_ERRORS = "errors"
TRAFFIC_DATA_PACKETS = "packets"
TRAFFIC_DATA_DROPPED = "dropped"
TRAFFIC_DATA_LAST_ACTIVITY = "last_activity"
TRAFFIC_DATA_LAST_ACTIVITY_IN_SECONDS = "last_activity_in_seconds"

TRAFFIC_STATS_BPS_KEY = "bps"
TRAFFIC_STATS_BYTES = "bytes"

TRAFFIC_DATA_DIRECTION_SENT = "tx"
TRAFFIC_DATA_DIRECTION_RECEIVED = "rx"

TRAFFIC_DATA_DIRECTIONS = [TRAFFIC_DATA_DIRECTION_SENT, TRAFFIC_DATA_DIRECTION_RECEIVED]

TRAFFIC_DATA_INTERFACE_ITEMS = {
    TRAFFIC_STATS_BPS_KEY: TRAFFIC_DATA_RATE,
    TRAFFIC_STATS_BYTES: TRAFFIC_DATA_TOTAL,
    TRAFFIC_DATA_ERRORS: TRAFFIC_DATA_ERRORS,
    TRAFFIC_DATA_PACKETS: TRAFFIC_DATA_PACKETS,
    TRAFFIC_DATA_DROPPED: TRAFFIC_DATA_DROPPED,
}

TRAFFIC_DATA_DEVICE_ITEMS = {
    TRAFFIC_DATA_RATE: TRAFFIC_DATA_RATE,
    TRAFFIC_STATS_BYTES: TRAFFIC_DATA_TOTAL,
}

INTERFACES_MAIN_MAP = [
    INTERFACE_DATA_UP,
    INTERFACE_DATA_LINK_UP,
    INTERFACE_DATA_SPEED,
    INTERFACE_DATA_DUPLEX,
    INTERFACE_DATA_MAC,
]

DISCOVER_DEVICE_ITEMS = [
    DEVICE_DATA_NAME,
    DISCOVER_DATA_PRODUCT,
    SYSTEM_STATS_DATA_UPTIME,
    DISCOVER_DATA_FW_VERSION,
    "system_status",
]

WS_CLOSING_MESSAGE = [
    aiohttp.WSMsgType.CLOSE,
    aiohttp.WSMsgType.CLOSED,
    aiohttp.WSMsgType.CLOSING,
]

SUPPORTED_INTERFACES = [
    InterfaceTypes.ETHERNET,
    InterfaceTypes.BRIDGE,
    InterfaceTypes.SWITCH,
    InterfaceTypes.OPEN_VPN,
    InterfaceTypes.WIREGUARD,
]

SUPPORTED_DYNAMIC_INTERFACES = [
    DynamicInterfaceTypes.PPPOE,
    DynamicInterfaceTypes.VIRTUAL_TUNNEL,
    DynamicInterfaceTypes.BONDING,
]

ATTR_UNIT_INFORMATION = "information"
ATTR_UNIT_RATE = "rate"
ATTR_UNIT_CONVERTOR = "unit_convertor"

UNIT_MAPPING = {
    str(UnitOfInformation.BYTES).lower(): {
        ATTR_UNIT_INFORMATION: UnitOfInformation.BYTES,
        ATTR_UNIT_RATE: UnitOfDataRate.BYTES_PER_SECOND,
        ATTR_UNIT_CONVERTOR: lambda v: v,
    },
    str(UnitOfInformation.KILOBYTES).lower(): {
        ATTR_UNIT_INFORMATION: UnitOfInformation.KILOBYTES,
        ATTR_UNIT_RATE: UnitOfDataRate.KILOBYTES_PER_SECOND,
        ATTR_UNIT_CONVERTOR: lambda v: v / 1024,
    },
    str(UnitOfInformation.MEGABYTES).lower(): {
        ATTR_UNIT_INFORMATION: UnitOfInformation.MEGABYTES,
        ATTR_UNIT_RATE: UnitOfDataRate.MEGABYTES_PER_SECOND,
        ATTR_UNIT_CONVERTOR: lambda v: v / 1024 / 1024,
    },
}

DEFAULT_UNIT = str(UnitOfInformation.BYTES)

ALL_EDGE_OS_UNITS = [str(unit) for unit in list(UnitOfEdgeOS)]

SUPPORTED_REMOVED_ENTITIES_DEVICE_TYPES = [
    DeviceTypes.DEVICE,
    DeviceTypes.INTERFACE,
]

ENTITY_VALIDATIONS = {
    EntityValidation.MONITORED: lambda is_monitored, is_admin: is_monitored,
    EntityValidation.ADMIN_ONLY: lambda is_monitored, is_admin: is_admin,
    EntityValidation.NON_ADMIN_ONLY: lambda is_monitored, is_admin: not is_admin,
}
