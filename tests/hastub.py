"""Minimal Home Assistant / aiohttp stubs so the integration modules can be imported."""
from dataclasses import dataclass
from enum import StrEnum as _StrEnum
import re
import sys
import types


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class WSMsgType:
    CLOSE = 1
    CLOSED = 2
    CLOSING = 3
    ERROR = 4
    TEXT = 5


class ClientSession:
    def __init__(self, *a, **k):
        self.closed = False
        self.headers = {}

    async def close(self):
        self.closed = True


class CookieJar:
    def __init__(self, *a, **k):
        pass


class UnitOfInformation(_StrEnum):
    BYTES = "B"
    KILOBYTES = "kB"
    MEGABYTES = "MB"


class UnitOfDataRate(_StrEnum):
    BYTES_PER_SECOND = "B/s"
    KILOBYTES_PER_SECOND = "kB/s"
    MEGABYTES_PER_SECOND = "MB/s"


class UnitOfTime(_StrEnum):
    SECONDS = "s"


class Platform(_StrEnum):
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"
    DEVICE_TRACKER = "device_tracker"
    UPDATE = "update"


class EntityCategory(_StrEnum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    device_class: object = None
    icon: str | None = None
    entity_category: object = None
    native_unit_of_measurement: str | None = None
    state_class: object = None
    options: list | None = None
    native_max_value: float | None = None
    native_min_value: float | None = None
    has_entity_name: bool = False


@dataclass(frozen=True, kw_only=True)
class BinarySensorEntityDescription(EntityDescription):
    pass


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    pass


@dataclass(frozen=True, kw_only=True)
class SwitchEntityDescription(EntityDescription):
    pass


@dataclass(frozen=True, kw_only=True)
class SelectEntityDescription(EntityDescription):
    pass


@dataclass(frozen=True, kw_only=True)
class NumberEntityDescription(EntityDescription):
    pass


@dataclass(frozen=True, kw_only=True)
class UpdateEntityDescription(EntityDescription):
    pass


class _DeviceClass(_StrEnum):
    UPDATE = "update"
    CONNECTIVITY = "connectivity"
    TIMESTAMP = "timestamp"
    DATA_RATE = "data_rate"
    DATA_SIZE = "data_size"


class _StateClass(_StrEnum):
    MEASUREMENT = "measurement"
    TOTAL_INCREASING = "total_increasing"


class DataUpdateCoordinator:
    def __init__(
        self, hass, logger, name=None, update_interval=None, update_method=None
    ):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.update_method = update_method
        self.last_update_success = True

    async def async_request_refresh(self):
        pass

    async def async_refresh(self):
        pass


class UpdateFailed(Exception):
    pass


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


# One distinct class per platform. A shared base would make the integration's
# `class X(IntegrationBaseEntity, SwitchEntity)` fail with an MRO conflict.
class BinarySensorEntity:
    pass


class SensorEntity:
    pass


class SwitchEntity:
    pass


class NumberEntity:
    pass


class SelectEntity:
    pass


class ScannerEntity:
    pass


class UpdateEntity:
    pass


class SourceType(_StrEnum):
    ROUTER = "router"


class FlowHandler:
    pass


class ConfigFlow:
    pass


class OptionsFlow:
    pass


class _Store:
    def __init__(self, *a, **k):
        pass


class _Handlers:
    @staticmethod
    def register(_domain):
        return lambda cls: cls


def callback(fn):
    return fn


def slugify(value):
    """Close enough to Home Assistant's own, which this stands in for.

    Every run of characters that is not alphanumeric collapses to a single
    underscore, so `WAN_OUT:760` becomes `wan_out_760` rather than keeping the
    colon a naive implementation would leave behind.
    """
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value))

    return text.strip("_").lower()


REDACTED = "**REDACTED**"


def async_redact_data(data, to_redact):
    """Home Assistant's redaction helper, reproduced so the key list can be tested.

    The algorithm belongs to Home Assistant and is stable; what is worth
    asserting against is the set of keys the integration asks it to redact.
    """
    if not isinstance(data, (dict, list)):
        return data

    if isinstance(data, list):
        return [async_redact_data(item, to_redact) for item in data]

    redacted = {**data}

    for key, value in redacted.items():
        if value is None:
            continue

        if isinstance(value, str) and not value:
            continue

        if key in to_redact:
            redacted[key] = REDACTED

        elif isinstance(value, (dict, list)):
            redacted[key] = async_redact_data(value, to_redact)

    return redacted


def install(stub_aiohttp: bool = True):
    """Stub what the integration imports at module level.

    `stub_aiohttp=False` leaves the real aiohttp in place, so the same modules
    can be driven against an actual router - which is what `tools/probe_router.py`
    does. Every suite here wants the stub, so that is the default.
    """
    if stub_aiohttp:
        _module(
            "aiohttp",
            WSMsgType=WSMsgType,
            ClientSession=ClientSession,
            CookieJar=CookieJar,
        )

        def create_clientsession(**kwargs):
            return ClientSession()

    else:
        import aiohttp

        def create_clientsession(**kwargs):
            return aiohttp.ClientSession()

    _module("voluptuous", Schema=object, Optional=object, Required=object)
    _module("cryptography")
    _module(
        "cryptography.fernet",
        InvalidToken=type("InvalidToken", (Exception,), {}),
        Fernet=object,
    )

    _module("homeassistant")
    _module(
        "homeassistant.const",
        StrEnum=_StrEnum,
        UnitOfInformation=UnitOfInformation,
        UnitOfDataRate=UnitOfDataRate,
        UnitOfTime=UnitOfTime,
        Platform=Platform,
        EntityCategory=EntityCategory,
        PERCENTAGE="%",
        ATTR_STATE="state",
        ATTR_ICON="icon",
        CONF_NAME="name",
        CONF_HOST="host",
        CONF_PASSWORD="password",
        CONF_PATH="path",
        CONF_PORT="port",
        CONF_SSL="ssl",
        CONF_USERNAME="username",
        EVENT_HOMEASSISTANT_START="homeassistant_start",
    )
    _module(
        "homeassistant.core",
        HomeAssistant=object,
        callback=callback,
        Event=object,
    )
    _module(
        "homeassistant.config_entries",
        ConfigEntry=object,
        ConfigFlow=ConfigFlow,
        OptionsFlow=OptionsFlow,
        HANDLERS=_Handlers,
        CONN_CLASS_LOCAL_POLL="local_poll",
        STORAGE_VERSION=1,
    )
    _module("homeassistant.data_entry_flow", FlowHandler=FlowHandler)
    _module(
        "homeassistant.exceptions",
        HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
        ConfigEntryNotReady=type("ConfigEntryNotReady", (Exception,), {}),
    )
    _module("homeassistant.helpers")
    _module(
        "homeassistant.helpers.device_registry",
        DeviceInfo=dict,
        DeviceEntry=object,
        async_get=lambda hass: None,
    )
    _module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: None,
        async_entries_for_device=lambda *a, **k: [],
    )
    _module(
        "homeassistant.helpers.dispatcher",
        async_dispatcher_connect=lambda *a, **k: (lambda: None),
        async_dispatcher_send=lambda *a, **k: None,
        dispatcher_send=lambda *a, **k: None,
    )
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=UpdateFailed,
        CoordinatorEntity=CoordinatorEntity,
    )
    _module(
        "homeassistant.helpers.aiohttp_client",
        async_create_clientsession=create_clientsession,
    )
    _module("homeassistant.helpers.storage", Store=_Store)
    _module("homeassistant.helpers.json", JSONEncoder=object)
    _module("homeassistant.helpers.translation", async_get_translations=None)
    _module("homeassistant.helpers.entity", EntityDescription=EntityDescription)
    _module("homeassistant.util", slugify=slugify)

    _module("homeassistant.components")
    _module(
        "homeassistant.components.diagnostics",
        async_redact_data=async_redact_data,
        REDACTED=REDACTED,
    )
    _module(
        "homeassistant.components.device_tracker",
        ATTR_IP="ip",
        ATTR_MAC="mac",
        ScannerEntity=ScannerEntity,
        SourceType=SourceType,
    )
    _module(
        "homeassistant.components.homeassistant",
        SERVICE_RELOAD_CONFIG_ENTRY="reload_config_entry",
    )
    _module(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=_DeviceClass,
        BinarySensorEntityDescription=BinarySensorEntityDescription,
        BinarySensorEntity=BinarySensorEntity,
    )
    _module(
        "homeassistant.components.number",
        NumberEntityDescription=NumberEntityDescription,
        NumberEntity=NumberEntity,
    )
    _module(
        "homeassistant.components.select",
        SelectEntityDescription=SelectEntityDescription,
        SelectEntity=SelectEntity,
    )
    _module(
        "homeassistant.components.sensor",
        SensorDeviceClass=_DeviceClass,
        SensorEntityDescription=SensorEntityDescription,
        SensorStateClass=_StateClass,
        SensorEntity=SensorEntity,
    )
    _module(
        "homeassistant.components.switch",
        SwitchEntityDescription=SwitchEntityDescription,
        SwitchEntity=SwitchEntity,
    )
    _module(
        "homeassistant.components.update",
        UpdateEntityDescription=UpdateEntityDescription,
        UpdateEntity=UpdateEntity,
    )
