from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timedelta
import logging
from typing import Optional, Any, cast

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity,
)
from homeassistant.util import dt as dt_util, slugify

from .vendor.iqua_softener import (
    IquaSoftener,
    IquaSoftenerData,
    IquaSoftenerVolumeUnit,
    IquaSoftenerException,
)

from homeassistant import config_entries, core
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE
from homeassistant.const import UnitOfVolume
from homeassistant.const import UnitOfVolumeFlowRate

from .const import (
    DOMAIN,
    CONF_DEVICE_SERIAL_NUMBER,
    CONF_PRODUCT_SERIAL_NUMBER,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def _check_water_shutoff_valve_available(coordinator) -> bool:
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


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    config = hass.data[DOMAIN][config_entry.entry_id]
    if config_entry.options:
        config.update(config_entry.options)
    
    # Get device serial number for entity naming (prefer device_sn, fallback to product_sn)
    device_serial_number = config.get(CONF_DEVICE_SERIAL_NUMBER) or config.get(CONF_PRODUCT_SERIAL_NUMBER)
    if not device_serial_number:
        _LOGGER.error("No device or product serial number found in config")
        return

    # Use the shared coordinator from __init__.py
    coordinator = config["coordinator"]
    
    # Authentication is already validated in __init__.py, so coordinator.data should be available
    if coordinator.data is None:
        _LOGGER.error("No data available from coordinator - authentication may have failed")
        return

    # Define all sensors except water shutoff valve state (which is conditional)
    base_sensors: list[IquaSoftenerSensor] = []
    
    # Add regular sensors with entity descriptions
    for clz, entity_description in (
        (
            IquaSoftenerStateSensor,
            SensorEntityDescription(key="State", name="State"),
        ),
        # Date/time sensor removed - not useful for users
        (
            IquaSoftenerRegenerationStatusSensor,
            SensorEntityDescription(
                key="REGENERATION_STATUS",
                name="Regeneration Status",
                icon="mdi:refresh-circle",
            ),
        ),
        (
            IquaSoftenerRegenerationTimeRemainingSensor,
            SensorEntityDescription(
                key="REGENERATION_TIME_REMAINING",
                name="Regeneration Time Remaining",
                device_class=SensorDeviceClass.DURATION,
                native_unit_of_measurement="s",
                icon="mdi:timer-sand",
            ),
        ),
        (
            IquaSoftenerLastRegenerationSensor,
            SensorEntityDescription(
                key="LAST_REGENERATION",
                name="Last regeneration",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
        ),
        (
            IquaSoftenerOutOfSaltEstimatedDaySensor,
            SensorEntityDescription(
                key="OUT_OF_SALT_ESTIMATED_DAY",
                name="Out of salt estimated day",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
        ),
        (
            IquaSoftenerSaltLevelSensor,
            SensorEntityDescription(
                key="SALT_LEVEL",
                name="Salt level",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=PERCENTAGE,
            ),
        ),
        (
            IquaSoftenerAvailableWaterSensor,
            SensorEntityDescription(
                key="AVAILABLE_WATER",
                name="Available water",
                state_class=SensorStateClass.TOTAL,
                device_class=SensorDeviceClass.WATER,
                icon="mdi:water",
            ),
        ),
        (
            IquaSoftenerWaterCurrentFlowSensor,
            SensorEntityDescription(
                key="WATER_CURRENT_FLOW",
                name="Water current flow",
                device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:water-pump",
            ),
        ),
        (
            IquaSoftenerWaterUsageTodaySensor,
            SensorEntityDescription(
                key="WATER_USAGE_TODAY",
                name="Today water usage",
                state_class=SensorStateClass.TOTAL_INCREASING,
                device_class=SensorDeviceClass.WATER,
                icon="mdi:water-minus",
            ),
        ),
        (
            IquaSoftenerWaterUsageDailyAverageSensor,
            SensorEntityDescription(
                key="WATER_USAGE_DAILY_AVERAGE",
                name="Water usage daily average",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:water-circle",
            ),
        ),
        (
            IquaSoftenerWiFiSignalStrengthSensor,
            SensorEntityDescription(
                key="WIFI_SIGNAL_STRENGTH",
                name="WiFi signal strength",
                state_class=SensorStateClass.MEASUREMENT,
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement="dBm",
                icon="mdi:wifi",
            ),
        ),
        (
            IquaSoftenerWaterHardnessSensor,
            SensorEntityDescription(
                key="WATER_HARDNESS",
                name="Water hardness",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement="gr/gal",
                icon="mdi:water-check",
            ),
        ),
    ):
        base_sensors.append(clz(coordinator, device_serial_number, entity_description))
    
    # Add WebSocket connection sensor (special case - no entity description)
    base_sensors.append(IquaSoftenerWebSocketConnectionSensor(coordinator, device_serial_number))
    
    # Check if device has water shutoff valve and add the sensor conditionally
    has_valve = await _check_water_shutoff_valve_available(coordinator)
    if has_valve:
        _LOGGER.info("Device has water shutoff valve - adding valve state sensor")
        valve_sensor = IquaSoftenerWaterShutoffValveStateSensor(
            coordinator, 
            device_serial_number, 
            SensorEntityDescription(
                key="WATER_SHUTOFF_VALVE_STATE",
                name="Water shutoff valve state",
                icon="mdi:valve",
            )
        )
        base_sensors.append(valve_sensor)
    else:
        _LOGGER.info("Device does not have water shutoff valve - skipping valve state sensor")
    
    sensors = base_sensors
    
    # Add sensors to Home Assistant
    async_add_entities(sensors)
    
    # Force immediate update of all sensors with current data
    if coordinator.data is not None:
        _LOGGER.info("Initializing sensor values immediately with current data...")
        for sensor in sensors:
            try:
                # Skip WebSocket connection sensor as it doesn't use coordinator data
                if isinstance(sensor, IquaSoftenerWebSocketConnectionSensor):
                    sensor._handle_coordinator_update()
                    sensor.async_write_ha_state()
                    continue
                
                # Cast coordinator data to the expected type
                coordinator_data = coordinator.data
                if isinstance(coordinator_data, dict):
                    # If it's still a dict, we can't process it
                    _LOGGER.warning("Coordinator data is not in expected format for sensor %s", sensor.entity_description.name)
                    continue
                
                sensor.update(coordinator_data)
                sensor.async_write_ha_state()
            except Exception as err:
                sensor_name = getattr(sensor, 'entity_description', None)
                if sensor_name:
                    sensor_name = sensor_name.name
                else:
                    sensor_name = getattr(sensor, '_attr_name', 'Unknown')
                _LOGGER.error("Error initializing sensor %s: %s", sensor_name, err)
        _LOGGER.info("All sensors initialized with immediate values")
    else:
        _LOGGER.warning("No data available for immediate sensor initialization")


class IquaSoftenerCoordinator(DataUpdateCoordinator):
    """Coordinator for iQua Softener device data updates.
    
    Manages polling of iQua cloud API with exponential backoff on failures.
    API Reference: https://api.myiquaapp.com/v1/docs
    
    Features:
    - Periodic polling (configurable 1-60 minutes)
    - WebSocket support for real-time updates
    - Exponential backoff on repeated failures
    - Automatic recovery with fresh authentication
    - 30-second API timeout with error recovery
    """
    
    # Backoff strategy constants
    INITIAL_INTERVAL_MINUTES = DEFAULT_UPDATE_INTERVAL
    MAX_INTERVAL_MINUTES = 60  # Maximum 1 hour between retries
    BACKOFF_MULTIPLIER = 2  # Double interval on each failure
    
    def __init__(
        self,
        hass: core.HomeAssistant,
        iqua_softener: IquaSoftener,
        update_interval_seconds: int = DEFAULT_UPDATE_INTERVAL * 60,
        enable_websocket: bool = True,
        config_data: Optional[dict] = None,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="Iqua Softener",
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self._iqua_softener = iqua_softener
        self._enable_websocket = enable_websocket
        self._config_data = config_data or {}
        self._initial_update_interval = timedelta(seconds=update_interval_seconds)

        # Store credentials for authentication recovery
        self._username: Optional[str] = self._config_data.get("username")
        self._password: Optional[str] = self._config_data.get("password")
        self._device_serial_number = self._config_data.get("device_sn")
        self._product_serial_number = self._config_data.get("product_sn")

        # Flag to delay WebSocket start until after bootstrap
        self._websocket_start_delayed = False
        self._websocket_update_scheduled = False
        
        # Backoff strategy tracking
        self._failure_count = 0
        
        # Register WebSocket data update callback once during initialization
        # This callback syncs coordinator data when WebSocket properties update
        def on_websocket_update(property_name: str):
            """Callback when WebSocket data updates - sync coordinator data."""
            self.hass.loop.call_soon_threadsafe(
                self._schedule_websocket_update,
                property_name,
            )
        
        self._iqua_softener.set_websocket_data_update_callback(on_websocket_update)

        _LOGGER.info(
            "IquaSoftenerCoordinator initialized with %d second update interval (%.1f minutes), WebSocket: %s",
            update_interval_seconds,
            update_interval_seconds / 60,
            enable_websocket,
        )

    @callback
    def _schedule_websocket_update(self, property_name: str) -> None:
        """Schedule one coordinator update for a burst of WebSocket messages."""
        _LOGGER.debug("WebSocket property updated: %s - scheduling coordinator update", property_name)
        if self._websocket_update_scheduled:
            return

        self._websocket_update_scheduled = True
        self.hass.async_create_task(self._async_update_data_from_websocket())

    async def _async_update_data_from_websocket(self):
        """Update coordinator data from current in-memory state without API call.
        
        WebSocket updates the _iqua_softener object in memory. This method reads
        the current state and updates the coordinator's cached data, allowing
        sensors to reflect real-time changes without making API calls.
        """
        try:
            await asyncio.sleep(0)
            if self.data is None:
                return

            # Rebuild coordinator data from in-memory state (cache + realtime updates)
            data = await self.hass.async_add_executor_job(
                lambda: self._iqua_softener.get_data(use_cache_only=True)
            )

            # Update coordinator data without rescheduling the periodic poll.
            # This directly updates self.data and notifies listeners of changes.
            self.data = data
            self.last_update_success = True
            self.async_update_listeners()
            _LOGGER.debug("Coordinator data updated from WebSocket properties")
        except Exception as err:
            _LOGGER.debug("Error updating coordinator data from WebSocket: %s", err)
        finally:
            self._websocket_update_scheduled = False

    async def async_start_websocket(self):
        """Start the WebSocket connection using library's implementation."""
        if not self._enable_websocket:
            _LOGGER.info("WebSocket disabled, skipping connection")
            return
        
        # Check if WebSocket is already running to prevent duplicate connections
        if self._iqua_softener.websocket_connected or self._iqua_softener._websocket_running:
            _LOGGER.debug("WebSocket already running, skipping start")
            return

        try:
            _LOGGER.info("Starting WebSocket using library's built-in implementation...")
            # Callback is already registered in __init__, just start the connection
            await self.hass.async_add_executor_job(self._iqua_softener.start_websocket)
            _LOGGER.info("WebSocket started successfully using library")
        except Exception as err:
            _LOGGER.error("Failed to start library WebSocket: %s", err)

    async def async_restart_websocket(self):
        """Restart the WebSocket connection."""
        _LOGGER.info("Restarting WebSocket connection")
        await self.async_stop_websocket()
        await self.async_start_websocket()

    async def async_stop_websocket(self):
        """Stop the WebSocket connection using library's implementation."""
        try:
            _LOGGER.info("Stopping WebSocket using library...")
            await self.hass.async_add_executor_job(self._iqua_softener.stop_websocket)
            _LOGGER.info("WebSocket stopped using library")
        except Exception as err:
            _LOGGER.error("Failed to stop library WebSocket: %s", err)

    async def async_retry_websocket(self):
        """Manually retry WebSocket connection."""
        _LOGGER.info("Manual WebSocket retry requested")
        await self.async_restart_websocket()

    async def async_force_update(self):
        """Force an immediate data update and sensor refresh."""
        _LOGGER.info("Manual data refresh requested - forcing API call and sensor updates")
        try:
            await self.async_refresh()
            _LOGGER.info("Manual data refresh completed successfully")
        except Exception as err:
            _LOGGER.error("Manual data refresh failed: %s", err)

    async def _async_update_data(self) -> IquaSoftenerData:
        """Fetch data from iQua cloud API with exponential backoff on failures.
        
        Implements backoff strategy:
        - Initial interval: configured update interval (1-60 minutes)
        - On failure: doubles interval up to 60 minutes
        - On success: resets to initial interval
        
        API Reference: https://api.myiquaapp.com/v1/docs
        Timeout: 30 seconds per request
        """
        _LOGGER.debug("Starting data fetch from iQua API...")
        
        # Start WebSocket after first successful data fetch (post-bootstrap)
        if (self._enable_websocket and 
            not self._websocket_start_delayed):
            _LOGGER.info("Starting WebSocket after successful initial API fetch...")
            self._websocket_start_delayed = True
            # Schedule WebSocket start as a background task to avoid blocking data fetch
            self.hass.async_create_task(self.async_start_websocket())
        
        try:
            data: Optional[IquaSoftenerData] = await self.hass.async_add_executor_job(
                lambda: self._iqua_softener.get_data()
            )
            
            if data is None:
                _LOGGER.error("API returned None data - sensors will show as unknown")
                raise UpdateFailed("API returned no data")
            
            # Reset failure counter and interval on success
            if self._failure_count > 0:
                _LOGGER.info(
                    "API recovered after %d failed attempts, resetting to normal polling interval",
                    self._failure_count,
                )
                self._failure_count = 0
                self.update_interval = self._initial_update_interval
            
            # Log timezone information for debugging
            if hasattr(data, 'device_date_time') and data.device_date_time:
                device_tz = data.device_date_time.tzinfo
                local_time = dt_util.as_local(data.device_date_time)
                _LOGGER.debug("Device time: %s (%s) -> Local: %s (%s)", 
                            data.device_date_time, device_tz, 
                            local_time, local_time.tzinfo)
            
            _LOGGER.info("✅ API refresh completed successfully - gallons used today: %s", data.today_use)
            return data
            
        except TypeError as err:
            # Handle library authentication issues
            if "'str' object is not callable" in str(err):
                _LOGGER.error("iQua library authentication error during API fetch: %s", err)
                # Try to recreate the iqua client to reset authentication state
                try:
                    _LOGGER.info("Attempting to recreate iQua client to reset authentication")
                    from .vendor.iqua_softener import IquaSoftener

                    if self._username and self._password:
                        self._iqua_softener = IquaSoftener(
                            self._username,
                            self._password,
                            device_serial_number=self._device_serial_number,
                            product_serial_number=self._product_serial_number,
                        )
                        # Try the request again with fresh client
                        data = await self.hass.async_add_executor_job(
                            lambda: self._iqua_softener.get_data()
                        )
                    else:
                        raise UpdateFailed("Missing credentials for authentication recovery")
                    
                    if data is None:
                        _LOGGER.error("API recovery returned None data")
                        raise UpdateFailed("API recovery returned no data")
                    
                    # Reset failure counter on successful recovery
                    self._failure_count = 0
                    self.update_interval = self._initial_update_interval
                    _LOGGER.info("✅ API recovery successful")

                    # Also restart WebSocket with fresh client if enabled
                    if self._enable_websocket:
                        self.hass.async_create_task(self.async_restart_websocket())

                    return data
                except Exception as recovery_err:
                    _LOGGER.error("Failed to recover from authentication error: %s", recovery_err)
                    self._apply_backoff_strategy()
                    raise UpdateFailed(f"iQua library authentication error: {err}")
            else:
                _LOGGER.error("Unexpected TypeError in iQua API call: %s", err)
                self._apply_backoff_strategy()
                raise UpdateFailed(f"Unexpected error: {err}")
        except IquaSoftenerException as err:
            _LOGGER.error("API data fetch failed: %s", err)
            self._apply_backoff_strategy()
            raise UpdateFailed(f"Get data failed: {err}")
        except Exception as err:
            _LOGGER.error("Unexpected error fetching API data: %s", err)
            self._apply_backoff_strategy()
            raise UpdateFailed(f"Unexpected error: {err}")
    
    def _apply_backoff_strategy(self) -> None:
        """Apply exponential backoff strategy on API failures.
        
        Increases polling interval up to 60 minutes to reduce load on API.
        Resets when API recovers.
        """
        self._failure_count += 1
        
        # Calculate new interval with exponential backoff
        minutes_multiplier = min(
            self.BACKOFF_MULTIPLIER ** (self._failure_count - 1),
            self.MAX_INTERVAL_MINUTES // self.INITIAL_INTERVAL_MINUTES,
        )
        new_interval_minutes = min(
            self.INITIAL_INTERVAL_MINUTES * minutes_multiplier,
            self.MAX_INTERVAL_MINUTES,
        )
        new_interval = timedelta(minutes=new_interval_minutes)
        
        if self.update_interval != new_interval:
            self.update_interval = new_interval
            _LOGGER.warning(
                "API error (attempt %d), applying exponential backoff - "
                "next retry in %d minutes",
                self._failure_count,
                new_interval_minutes,
            )


class IquaSoftenerSensor(SensorEntity, CoordinatorEntity, ABC):
    coordinator: IquaSoftenerCoordinator  # Type hint override for proper attribute access
    
    def __init__(
        self,
        coordinator: IquaSoftenerCoordinator,
        device_serial_number: str,
        entity_description: Optional[SensorEntityDescription] = None,
    ):
        super().__init__(coordinator)
        self._device_serial_number = device_serial_number
        if entity_description is not None:
            self._attr_unique_id = (
                f"{device_serial_number}_{entity_description.key}".lower()
            )
            self.entity_description = entity_description
            self.entity_id = (
                f"sensor.{slugify(device_serial_number)}_{slugify(entity_description.name)}"
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        try:
            if self.coordinator.data is None:
                _LOGGER.warning("%s: No data available from coordinator", self.entity_description.name)
                return
            
            # Cast coordinator data to the expected type
            coordinator_data = self.coordinator.data
            if isinstance(coordinator_data, dict):
                # If it's still a dict, we can't process it
                _LOGGER.warning("%s: Coordinator data is not in expected format", self.entity_description.name)
                return
            
            self.update(coordinator_data)
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error updating %s sensor: %s", self.entity_description.name, err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_serial_number)},
            "name": f"Iqua Softener {self._device_serial_number}",
            "manufacturer": "Iqua",
            "model": "Water Softener",
        }

    @abstractmethod
    def update(self, data: IquaSoftenerData): ...


class IquaSoftenerStateSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            old_value = getattr(self, '_attr_native_value', None)
            self._attr_native_value = str(data.state.value)
            
            if old_value != self._attr_native_value:
                _LOGGER.debug("State changed: %s → %s", old_value, self._attr_native_value)
        except Exception as err:
            _LOGGER.error("Error updating state sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = "Unknown"


# IquaSoftenerDeviceDateTimeSensor class removed - sensor no longer exposed
# The underlying data.device_date_time field is still available for debugging


class IquaSoftenerLastRegenerationSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            # Calculate last regeneration date in Home Assistant's local timezone
            now_local = dt_util.now()
            last_regen = now_local - timedelta(days=data.days_since_last_regeneration)
            # Set to midnight of that day
            self._attr_native_value = last_regen.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception as err:
            _LOGGER.error("Error updating last regeneration sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = None


class IquaSoftenerRegenerationStatusSensor(IquaSoftenerSensor):
    """Sensor for regeneration status from enriched data."""
    
    def update(self, data: IquaSoftenerData):
        try:
            # Get regeneration status from enriched data
            # Note: enriched_data is already the water_treatment object from the API
            regeneration_status = "unknown"
            
            if hasattr(data, 'enriched_data') and data.enriched_data:
                regeneration = data.enriched_data.get('regeneration', {})
                regeneration_status = regeneration.get('regeneration_status', 'unknown')
            
            # Capitalize for display (e.g., "none" -> "None", "regenerating" -> "Regenerating")
            self._attr_native_value = regeneration_status.replace('_', ' ').title()
            
        except Exception as err:
            _LOGGER.error("Error updating regeneration status sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = "Unknown"


class IquaSoftenerRegenerationTimeRemainingSensor(IquaSoftenerSensor):
    """Sensor for regeneration time remaining in seconds."""
    
    def update(self, data: IquaSoftenerData):
        try:
            # Check regeneration status - if not regenerating, time remaining should be 0
            regeneration_status = "unknown"
            if hasattr(data, 'enriched_data') and data.enriched_data:
                regeneration = data.enriched_data.get('regeneration', {})
                regeneration_status = regeneration.get('regeneration_status', 'unknown')
            
            # If not regenerating, zero out the time remaining
            if regeneration_status != "regenerating":
                self._attr_native_value = 0
                return
            
            # Try to get real-time value from WebSocket first
            realtime_value = self.coordinator._iqua_softener.get_realtime_property(
                "regen_time_rem_secs"
            )
            
            if realtime_value is not None:
                self._attr_native_value = int(realtime_value)
            else:
                # Fall back to enriched_data from periodic API calls
                # Note: enriched_data is already the water_treatment object from the API
                regen_time_rem = None
                
                if hasattr(data, 'enriched_data') and data.enriched_data:
                    regeneration = data.enriched_data.get('regeneration', {})
                    regen_time_rem = regeneration.get('regen_time_rem_secs')
                
                # Set the value in seconds (or 0 if not available/not regenerating)
                self._attr_native_value = int(regen_time_rem) if regen_time_rem is not None else 0
            
        except Exception as err:
            _LOGGER.error("Error updating regeneration time remaining sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = 0


class IquaSoftenerOutOfSaltEstimatedDaySensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            # Calculate out of salt date in Home Assistant's local timezone
            now_local = dt_util.now()
            out_of_salt_date = now_local + timedelta(days=data.out_of_salt_estimated_days)
            # Set to midnight of that day
            self._attr_native_value = out_of_salt_date.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception as err:
            _LOGGER.error("Error updating out of salt estimation sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = None


class IquaSoftenerSaltLevelSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            old_value = getattr(self, '_attr_native_value', None)
            self._attr_native_value = data.salt_level_percent
            
            if old_value != self._attr_native_value and isinstance(self._attr_native_value, (int, float)):
                _LOGGER.debug("Salt level changed: %s%% → %s%%", old_value, self._attr_native_value)
        except Exception as err:
            _LOGGER.error("Error updating salt level sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = None

    @property
    def icon(self) -> Optional[str]:
        if self._attr_native_value is not None and isinstance(self._attr_native_value, (int, float)):
            if self._attr_native_value > 75:
                return "mdi:signal-cellular-3"
            elif self._attr_native_value > 50:
                return "mdi:signal-cellular-2"
            elif self._attr_native_value > 25:
                return "mdi:signal-cellular-1"
            elif self._attr_native_value > 5:
                return "mdi:signal-cellular-outline"
            return "mdi:signal-off"
        else:
            return "mdi:signal"


class IquaSoftenerAvailableWaterSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            # Use converted_value from additional_properties if available, otherwise fall back to total_water_available
            if data.additional_properties and "treated_water_avail_gals" in data.additional_properties:
                prop = data.additional_properties["treated_water_avail_gals"]
                self._attr_native_value = prop.get(
                    "converted_value",
                    prop.get("value", data.total_water_available),
                )
                # Set unit based on converted_units
                units = prop.get("converted_units", "Gallons")
                self._attr_native_unit_of_measurement = UnitOfVolume.LITERS if units == "Liters" else UnitOfVolume.GALLONS

            # Set last reset to last regeneration in local timezone
            now_local = dt_util.now()
            last_regen = now_local - timedelta(days=data.days_since_last_regeneration)
            self._attr_last_reset = last_regen.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception as err:
            _LOGGER.error("Error updating available water sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = 0


class IquaSoftenerWaterCurrentFlowSensor(IquaSoftenerSensor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ensure the device_class is set even if the description is mutated later
        self._attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE

    def update(self, data: IquaSoftenerData):
        try:
            # Use the library's get_realtime_property method for real-time flow data
            coordinator = cast(IquaSoftenerCoordinator, self.coordinator)
            realtime_flow = coordinator._iqua_softener.get_realtime_property(
                "current_water_flow_gpm"
            )
            
            old_value = getattr(self, '_attr_native_value', None)
            
            if realtime_flow is not None:
                # Use real-time WebSocket data
                self._attr_native_value = realtime_flow
                if old_value != self._attr_native_value:
                    _LOGGER.debug("Water flow updated from WebSocket: %s", realtime_flow)
            else:
                # Fall back to regular API data
                self._attr_native_value = data.current_water_flow
                if old_value != self._attr_native_value:
                    _LOGGER.debug("Water flow updated from API: %s", self._attr_native_value)

            self._attr_native_unit_of_measurement = (
                UnitOfVolumeFlowRate.LITERS_PER_MINUTE
                if data.volume_unit == IquaSoftenerVolumeUnit.LITERS
                else UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
            )
        except Exception as err:
            _LOGGER.error("Error updating water flow sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = 0


class IquaSoftenerWaterUsageTodaySensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            old_value = getattr(self, '_attr_native_value', None)
            # Use converted_value from additional_properties if available
            if data.additional_properties and "gallons_used_today" in data.additional_properties:
                prop = data.additional_properties["gallons_used_today"]
                self._attr_native_value = prop.get(
                    "converted_value",
                    prop.get("value", data.today_use),
                )
                # Set unit based on converted_units
                units = prop.get("converted_units", "Gallons")
                self._attr_native_unit_of_measurement = UnitOfVolume.LITERS if units == "Liters" else UnitOfVolume.GALLONS
            else:
                self._attr_native_value = 0
                self._attr_native_unit_of_measurement = (
                    UnitOfVolume.LITERS
                    if data.volume_unit == IquaSoftenerVolumeUnit.LITERS
                    else UnitOfVolume.GALLONS
                )
            if old_value != self._attr_native_value:
                _LOGGER.debug("Today's water usage changed: %s → %s %s", 
                            old_value, self._attr_native_value, self._attr_native_unit_of_measurement)
        except Exception as err:
            _LOGGER.error("Error updating today's water usage sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = 0


class IquaSoftenerWaterUsageDailyAverageSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            # Use converted_value from additional_properties if available
            if data.additional_properties and "avg_daily_use_gals" in data.additional_properties:
                prop = data.additional_properties["avg_daily_use_gals"]
                self._attr_native_value = prop.get(
                    "converted_value",
                    prop.get("value", data.average_daily_use),
                )
                # Set unit based on converted_units
                units = prop.get("converted_units", "Gallons")
                self._attr_native_unit_of_measurement = UnitOfVolume.LITERS if units == "Liters" else UnitOfVolume.GALLONS

        except Exception as err:
            _LOGGER.error("Error updating daily average water usage sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = 0


class IquaSoftenerWaterShutoffValveStateSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            prop = (
                data.additional_properties.get("valve_pos_switch_enum")
                if data.additional_properties
                else None
            )
            if prop is not None:
                valve_state = prop.get("converted_value", prop.get("value"))
            elif hasattr(data, "water_shutoff_valve_state"):
                # Convert numeric state to text
                valve_state = data.water_shutoff_valve_state
            else:
                valve_state = None

            if valve_state is not None:
                if valve_state == 1:
                    self._attr_native_value = "Open"
                elif valve_state == 0:
                    self._attr_native_value = "Closed"
                else:
                    self._attr_native_value = f"Unknown ({valve_state})"
                return

            self._attr_native_value = "Unknown"
        except Exception as err:
            _LOGGER.error("Error updating water shutoff valve sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = "Unknown"

    @property
    def icon(self) -> Optional[str]:
        if self._attr_native_value == "Open":
            return "mdi:valve-open"
        elif self._attr_native_value == "Closed":
            return "mdi:valve-closed"
        else:
            return "mdi:valve"


class IquaSoftenerWiFiSignalStrengthSensor(IquaSoftenerSensor):
    """WiFi signal strength sensor that gets updated from WebSocket real-time data."""
    
    def update(self, data: IquaSoftenerData):
        try:
            # Use the library's get_realtime_property method for real-time WiFi signal data
            coordinator = cast(IquaSoftenerCoordinator, self.coordinator)
            realtime_signal = coordinator._iqua_softener.get_realtime_property(
                "rf_signal_strength_dbm"
            )
            
            old_value = getattr(self, '_attr_native_value', None)
            
            if realtime_signal is not None:
                # Use real-time WebSocket data
                self._attr_native_value = realtime_signal
                if old_value != self._attr_native_value:
                    _LOGGER.debug("WiFi signal strength updated from WebSocket: %s dBm", realtime_signal)
            else:
                # No API fallback for WiFi signal - only available via WebSocket
                self._attr_native_value = None
                
        except Exception as err:
            _LOGGER.error("Error updating WiFi signal strength sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = None

    @property
    def icon(self) -> Optional[str]:
        """Return icon based on signal strength."""
        if self._attr_native_value is None:
            return "mdi:wifi-off"
        
        # Signal strength typically ranges from -100 dBm (weak) to -30 dBm (strong)
        try:
            signal = float(self._attr_native_value) if isinstance(self._attr_native_value, (int, float)) else None
            if signal is None:
                return "mdi:wifi-off"
                
            if signal >= -50:
                return "mdi:wifi"
            elif signal >= -60:
                return "mdi:wifi-strength-3"
            elif signal >= -70:
                return "mdi:wifi-strength-2"
            elif signal >= -80:
                return "mdi:wifi-strength-1"
            else:
                return "mdi:wifi-strength-outline"
        except (ValueError, TypeError):
            return "mdi:wifi-off"


class IquaSoftenerWebSocketConnectionSensor(SensorEntity, CoordinatorEntity):
    """Sensor for WebSocket connection status."""
    
    coordinator: IquaSoftenerCoordinator  # Type hint override for proper attribute access
    
    def __init__(self, coordinator: IquaSoftenerCoordinator, device_serial_number: str):
        super().__init__(coordinator)
        self._device_serial_number = device_serial_number
        self._attr_name = "WebSocket Connection"
        self._attr_unique_id = f"{device_serial_number}_websocket_connection".lower()
        self.entity_id = f"sensor.{slugify(device_serial_number)}_websocket_connection"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["Connected", "Disconnected"]
        self._attr_icon = "mdi:lan-connect"
        
        # Register callback for WebSocket state changes
        def on_state_change(is_connected: bool):
            """Handle WebSocket connection state changes."""
            try:
                _LOGGER.debug("WebSocket state changed to: %s", "Connected" if is_connected else "Disconnected")
                self._attr_native_value = "Connected" if is_connected else "Disconnected"
                # Schedule state write on Home Assistant event loop
                if self.hass:
                    asyncio.run_coroutine_threadsafe(
                        self._async_write_ha_state_safe(),
                        self.hass.loop
                    )
            except Exception as err:
                _LOGGER.error("Error in WebSocket state change callback: %s", err)
        
        coordinator._iqua_softener.set_websocket_state_change_callback(on_state_change)
    
    async def _async_write_ha_state_safe(self):
        """Safely write HA state, checking if entity is added."""
        try:
            if hasattr(self, 'hass') and hasattr(self, 'entity_id'):
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.debug("Could not write HA state (entity may not be fully initialized): %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_serial_number)},
            "name": f"Iqua Softener {self._device_serial_number}",
            "manufacturer": "Iqua",
            "model": "Water Softener",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the sensor state when coordinator updates."""
        try:
            # Check WebSocket connection status directly from the iqua_softener instance
            is_connected = self.coordinator._iqua_softener.websocket_connected
            self._attr_native_value = "Connected" if is_connected else "Disconnected"
        except Exception as err:
            _LOGGER.error("Error updating WebSocket connection sensor: %s", err)
            self._attr_native_value = None


class IquaSoftenerWaterHardnessSensor(IquaSoftenerSensor):
    def update(self, data: IquaSoftenerData):
        try:
            self._attr_native_value = data.hardness_grains
        except Exception as err:
            _LOGGER.error("Error updating water hardness sensor: %s", err)
            if not hasattr(self, '_attr_native_value'):
                self._attr_native_value = None
