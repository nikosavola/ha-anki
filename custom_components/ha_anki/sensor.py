"""Sensor platform for the ha-anki integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AnkiConnectError
from .const import (
    CONF_CUSTOM_QUERIES,
    CUSTOM_QUERY_KEY_PREFIX,
    DOMAIN,
    SENSOR_KEYS,
    SYNC_SERVICE,
)
from .coordinator import AnkiConnectConfigEntry, AnkiConnectDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnkiConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AnkiConnect sensors from a config entry."""
    coordinator = entry.runtime_data
    custom_queries = entry.options.get(CONF_CUSTOM_QUERIES, {})

    entities = [
        AnkiConnectCardCountSensor(coordinator, entry, key) for key in SENSOR_KEYS
    ]
    entities.extend(
        AnkiConnectCardCountSensor(
            coordinator, entry, f"{CUSTOM_QUERY_KEY_PREFIX}{slug}", name=data[CONF_NAME]
        )
        for slug, data in custom_queries.items()
    )
    async_add_entities(entities)
    _prune_stale_entities(hass, entry, {entity.unique_id for entity in entities})

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SYNC_SERVICE, None, "async_sync")


def _prune_stale_entities(
    hass: HomeAssistant,
    entry: AnkiConnectConfigEntry,
    expected_unique_ids: set[str | None],
) -> None:
    """Remove sensor registry entries this entry no longer produces.

    Custom query sensors can be removed via the options flow; without this,
    their entity registry entries would linger forever as unavailable.
    Restricted to the sensor domain, since a future non-sensor platform on
    this same config entry shouldn't have its entities swept up here too.
    """
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            registry_entry.domain == Platform.SENSOR
            and registry_entry.unique_id not in expected_unique_ids
        ):
            registry.async_remove(registry_entry.entity_id)


class AnkiConnectCardCountSensor(
    CoordinatorEntity[AnkiConnectDataUpdateCoordinator], SensorEntity
):
    """Sensor reporting one AnkiConnect count value."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cards"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cards"

    def __init__(
        self,
        coordinator: AnkiConnectDataUpdateCoordinator,
        entry: AnkiConnectConfigEntry,
        key: str,
        *,
        name: str | None = None,
    ) -> None:
        """Initialize the sensor for one card-count query.

        `name` is set for user-defined custom queries, which have no
        translation key since their display name is chosen at runtime.
        """
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        if name is not None:
            self._attr_name = name
        else:
            self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Anki",
        )

    @property
    def native_value(self) -> int | None:
        """The current value for this sensor's key.

        None for a custom query AnkiConnect rejected (e.g. invalid syntax
        after an Anki upgrade), rather than taking the whole entry unavailable.
        """
        return self.coordinator.data.get(self._key)

    async def async_sync(self) -> None:
        """Trigger an AnkiConnect sync, then refresh sensor state immediately.

        Raises:
            HomeAssistantError: If AnkiConnect can't be reached, or reports
                an error (e.g. no AnkiWeb account configured).

        """
        try:
            await self.coordinator.client.sync()
        except AnkiConnectError as err:
            raise HomeAssistantError(f"Failed to sync Anki: {err}") from err
        await self.coordinator.async_request_refresh()
