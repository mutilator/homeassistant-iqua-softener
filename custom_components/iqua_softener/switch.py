import logging
from typing import Any, Optional, cast
import asyncio

from homeassistant.core import callback
from homeassistant.util import slugify
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.switch import SwitchEntity

from .vendor.iqua_softener import IquaSoftenerData, IquaSoftenerException

from homeassistant import config_entries, core
from .const import DOMAIN, CONF_DEVICE_SERIAL_NUMBER, CONF_PRODUCT_SERIAL_NUMBER, SWITCH_OPTIMISTIC_TIMEOUT
from .sensor import IquaSoftenerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Set up the Iqua Softener switch platform."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    if config_entry.options:
        config.update(config_entry.options)

    # Get device serial number (prefer device_sn, fallback to product_sn)
    device_serial_number = config.get(CONF_DEVICE_SERIAL_NUMBER) or config.get(CONF_PRODUCT_SERIAL_NUMBER)
    if not device_serial_number:
        _LOGGER.error("No device or product serial number found in config for switch setup")
        return

    # Use the shared coordinator from __init__.py
    coordinator = config["coordinator"]

    # Check if the device has a water shutoff valve before creating the switch
    if coordinator.data is None:
        _LOGGER.warning("No data available to check for water shutoff valve capability")
        return

    # Check if device has water shutoff valve installed
    if not await _check_water_shutoff_valve_available(coordinator):
        _LOGGER.info("Device does not have a water shutoff valve installed - skipping switch creation")
        return

    # Create the water shutoff valve switch only if device supports it
    switches = [IquaSoftenerWaterShutoffValveSwitch(coordinator, device_serial_number)]
    _LOGGER.info("Water shutoff valve switch created for device %s", device_serial_number)

    async_add_entities(switches)


async def _check_water_shutoff_valve_available(coordinator: IquaSoftenerCoordinator) -> bool:
    """Check if the device has a water shutoff valve installed."""
    try:
        # Use the library method to check if device has water shutoff valve
        has_valve = await coordinator.hass.async_add_executor_job(
            coordinator._iqua_softener.has_water_shutoff_valve
        )
        _LOGGER.debug("Water shutoff valve availability check: %s", has_valve)
        return has_valve
        
    except Exception as err:
        _LOGGER.error("Error checking water shutoff valve availability: %s", err)
        return False


class IquaSoftenerWaterShutoffValveSwitch(SwitchEntity, CoordinatorEntity):
    """Representation of the Iqua Softener water shutoff valve switch."""

    coordinator: IquaSoftenerCoordinator  # Type hint override for proper attribute access

    def __init__(
        self,
        coordinator: IquaSoftenerCoordinator,
        device_serial_number: str,
    ):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._device_serial_number = device_serial_number
        self._attr_unique_id = f"{device_serial_number}_water_shutoff_valve".lower()
        self._attr_name = "Water Shutoff Valve"
        self._attr_icon = "mdi:valve"
        self.entity_id = f"switch.{slugify(device_serial_number)}_water_shutoff_valve"
        self._optimistic_state = None
        self._optimistic_until = None

        # Get initial state
        if self.coordinator.data is not None:
            self.update_state(cast(IquaSoftenerData, self.coordinator.data))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self.update_state(cast(IquaSoftenerData, self.coordinator.data))
        self.async_write_ha_state()

    def update_state(self, data: Optional[IquaSoftenerData]) -> None:
        """Update the switch state based on coordinator data."""
        # If we're in optimistic mode and haven't reached the timeout, keep optimistic state
        if self._optimistic_state is not None and self._optimistic_until is not None:
            import time

            if time.time() < self._optimistic_until:
                self._attr_is_on = self._optimistic_state
                return
            else:
                # Optimistic period expired, clear it
                self._optimistic_state = None
                self._optimistic_until = None

        if data and data.water_shutoff_valve_state is not None:
            # 1 = open (on), 0 = closed (off)
            self._attr_is_on = bool(data.water_shutoff_valve_state)
        else:
            # "manual", "error" and friends are not on/off states
            self._attr_is_on = None

        self._attr_extra_state_attributes = {
            "valve_status": data.water_shutoff_valve_status if data else None,
            "error_code": data.water_shutoff_valve_error_code if data else None,
            "manual_override": (
                data.water_shutoff_valve_manual_override if data else None
            ),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the water shutoff valve (open the valve)."""
        # Set optimistic state immediately
        import time

        self._optimistic_state = True
        self._optimistic_until = time.time() + SWITCH_OPTIMISTIC_TIMEOUT
        self._attr_is_on = True
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self.coordinator._iqua_softener.open_water_shutoff_valve
            )
            # Wait a bit longer before refresh to allow valve to actually change
            await asyncio.sleep(3)
            # Request an immediate update after the action
            await self.coordinator.async_request_refresh()
        except IquaSoftenerException as err:
            # Clear optimistic state on error
            self._optimistic_state = None
            self._optimistic_until = None
            _LOGGER.error("Failed to open water shutoff valve: %s", err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the water shutoff valve (close the valve)."""
        # Set optimistic state immediately
        import time

        self._optimistic_state = False
        self._optimistic_until = time.time() + SWITCH_OPTIMISTIC_TIMEOUT
        self._attr_is_on = False
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self.coordinator._iqua_softener.close_water_shutoff_valve
            )
            # Wait a bit longer before refresh to allow valve to actually change
            await asyncio.sleep(3)
            # Request an immediate update after the action
            await self.coordinator.async_request_refresh()
        except IquaSoftenerException as err:
            # Clear optimistic state on error
            self._optimistic_state = None
            self._optimistic_until = None
            _LOGGER.error("Failed to close water shutoff valve: %s", err)
            raise

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_serial_number)},
            "name": f"Iqua Softener {self._device_serial_number}",
            "manufacturer": "Iqua",
            "model": "Water Softener",
        }
