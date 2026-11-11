"""Conditional resin maintenance alert using the shared coordinator snapshot."""

from homeassistant import config_entries, core
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_DEVICE_SERIAL_NUMBER, CONF_PRODUCT_SERIAL_NUMBER, DOMAIN
from .sensor import IquaSoftenerCoordinator
from .vendor.iqua_softener import IquaSoftenerData, IquaSoftenerState

RESIN_ALERT = BinarySensorEntityDescription(
    key="RESIN_ALERT",
    translation_key="resin_alert",
    device_class=BinarySensorDeviceClass.PROBLEM,
    icon="mdi:water-alert",
)


def _resin_alert_value(data: IquaSoftenerData | None) -> bool | None:
    """Prefer a semantic boolean, falling back to verified raw integer 0/1.

    A readable field is not proof of physical support on every device model.
    Never coerce missing, malformed, or arbitrary truthy values to clear/on.
    """
    if data is None:
        return None

    enriched = data.enriched_data
    status = (
        enriched.get("water_treatment_status") if isinstance(enriched, dict) else None
    )
    value = status.get("resin_alert") if isinstance(status, dict) else None
    if type(value) is bool:
        return value

    properties = data.additional_properties
    prop = properties.get("resin_alert") if isinstance(properties, dict) else None
    value = prop.get("value") if isinstance(prop, dict) else None
    if type(value) is int and value in (0, 1):
        return value == 1
    return None


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Create the alert only when setup data contains a readable resin state."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    if config_entry.options:
        config.update(config_entry.options)
    serial = config.get(CONF_DEVICE_SERIAL_NUMBER) or config.get(
        CONF_PRODUCT_SERIAL_NUMBER
    )
    coordinator = config["coordinator"]
    if serial and _resin_alert_value(coordinator.data) is not None:
        async_add_entities([IquaSoftenerResinAlert(coordinator, serial)])


class IquaSoftenerResinAlert(CoordinatorEntity, BinarySensorEntity):
    """A readable resin maintenance problem alert; no separate API polling."""

    _attr_has_entity_name = True
    entity_description = RESIN_ALERT

    def __init__(self, coordinator: IquaSoftenerCoordinator, device_serial_number: str):
        super().__init__(coordinator)
        self._device_serial_number = device_serial_number
        self._attr_unique_id = f"{device_serial_number}_{RESIN_ALERT.key}".lower()
        self.entity_id = (
            f"binary_sensor.{slugify(device_serial_number)}_resin_maintenance_alert"
        )

    @property
    def device_info(self):
        """Use the same device association as the existing upstream entities."""
        return {
            "identifiers": {(DOMAIN, self._device_serial_number)},
            "name": f"Iqua Softener {self._device_serial_number}",
            "manufacturer": "Iqua",
            "model": "Water Softener",
        }

    @property
    def available(self) -> bool:
        """Missing/invalid readings and failed updates never mean healthy."""
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.state != IquaSoftenerState.OFFLINE
            and _resin_alert_value(data) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Read the current snapshot rather than retaining an earlier state."""
        return _resin_alert_value(self.coordinator.data)
