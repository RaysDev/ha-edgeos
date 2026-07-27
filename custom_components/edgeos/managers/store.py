import logging

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class IntegrationStore(Store):
    """The integration's store, tolerant of a change in storage version.

    The version passed in comes from Home Assistant's own `STORAGE_VERSION`, so
    if that constant is ever bumped this store inherits the new number while the
    file on disk still carries the old one. Without a migration `Store` raises
    `NotImplementedError`, and both the stored settings and the key that
    decrypts the router password are lost.

    Nothing here needs converting - the contents are a flat dictionary of
    settings rather than a schema that evolves - so the migration hands the data
    back unchanged. The signature of the hook has varied across Home Assistant
    versions, which is why this one accepts whatever it is given and takes the
    data from the end.
    """

    async def _async_migrate_func(self, *args):
        _LOGGER.info("Storage version changed, keeping the stored configuration")

        return args[-1]
