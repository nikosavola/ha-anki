"""Sensor platform for the AnkiConnect integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AnkiConnectError
from .const import DOMAIN, SENSOR_KEYS, SYNC_SERVICE
from .coordinator import AnkiConnectConfigEntry, AnkiConnectDataUpdateCoordinator


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: AnkiConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AnkiConnect sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        AnkiConnectCardCountSensor(coordinator, entry, key) for key in SENSOR_KEYS
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SYNC_SERVICE, None, "async_sync")


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
    ) -> None:
        """Initialize the sensor for one card-count query."""
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Anki",
        )

    @property
    def native_value(self) -> int | None:
        """The current value for this sensor's key."""
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
