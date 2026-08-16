"""Test the iQua Softener sensor entities."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import replace
from datetime import datetime, timezone, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.iqua_softener.const import DOMAIN

from custom_components.iqua_softener.sensor import (
    IquaSoftenerCoordinator,
    IquaSoftenerStateSensor,
    # IquaSoftenerDeviceDateTimeSensor removed - sensor no longer exposed
    IquaSoftenerLastRegenerationSensor,
    IquaSoftenerOutOfSaltEstimatedDaySensor,
    IquaSoftenerSaltLevelSensor,
    IquaSoftenerAvailableWaterSensor,
    IquaSoftenerWaterCurrentFlowSensor,
    IquaSoftenerWaterUsageTodaySensor,
    IquaSoftenerWaterUsageDailyAverageSensor,
    IquaSoftenerWaterShutoffValveStateSensor,
    async_setup_entry,
    _check_water_shutoff_valve_available,
)
from custom_components.iqua_softener.vendor.iqua_softener import (
    IquaSoftenerData,
    IquaSoftenerState,
    IquaSoftenerVolumeUnit,
)


class TestIquaSoftenerCoordinator:
    """Test the IquaSoftenerCoordinator."""

    async def test_coordinator_initialization(self, hass, mock_iqua_softener, config_entry_data):
        """Test coordinator initialization."""
        coordinator = IquaSoftenerCoordinator(
            hass,
            mock_iqua_softener,
            update_interval_seconds=300,  # 5 minutes in seconds
            enable_websocket=True,
            config_data=config_entry_data,
        )

        assert coordinator._iqua_softener == mock_iqua_softener
        assert coordinator._enable_websocket is True
        assert coordinator._username == "test@example.com"
        assert coordinator._password == "testpass123"

    async def test_async_update_data_success(self, hass, mock_iqua_softener, mock_iqua_data):
        """Test successful data update."""
        coordinator = IquaSoftenerCoordinator(hass, mock_iqua_softener)
        mock_iqua_softener.get_data.return_value = mock_iqua_data

        result = await coordinator._async_update_data()

        assert result == mock_iqua_data
        mock_iqua_softener.get_data.assert_called_once()

    async def test_async_update_data_failure(self, hass, mock_iqua_softener):
        """Test data update failure."""
        coordinator = IquaSoftenerCoordinator(hass, mock_iqua_softener)
        mock_iqua_softener.get_data.return_value = None

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_websocket_disabled(self, hass, mock_iqua_softener):
        """Test WebSocket operations when disabled."""
        coordinator = IquaSoftenerCoordinator(hass, mock_iqua_softener, enable_websocket=False)

        await coordinator.async_start_websocket()
        mock_iqua_softener.start_websocket.assert_not_called()


class TestSensorEntities:
    """Test the sensor entities."""

    async def test_state_sensor(self, hass, mock_iqua_data):
        """Test the state sensor."""
        coordinator = MagicMock()
        coordinator.data = mock_iqua_data

        sensor = IquaSoftenerStateSensor(coordinator, "DEVICE123")
        sensor.update(mock_iqua_data)

        assert sensor._attr_native_value == "NORMAL"
        assert sensor.unique_id == "device123_state"

    # Date/time sensor test removed - sensor no longer exposed
    # The class still exists but is not instantiated

    async def test_state_sensor(self, hass, init_integration):
        """Test the state sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_state")
        assert state is not None
        assert state.state == "Online"

    async def test_last_regeneration_sensor(self, hass, init_integration):
        """Test the last regeneration sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_last_regeneration")
        assert state is not None

    async def test_out_of_salt_sensor(self, hass, init_integration):
        """Test the out of salt estimation sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_out_of_salt_estimated_day")
        assert state is not None

    async def test_salt_level_sensor(self, hass, init_integration):
        """Test the salt level sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_salt_level")
        assert state is not None
        assert state.state == "75"

    async def test_salt_level_sensor_icon(self, hass, init_integration, mock_iqua_data):
        """Test salt level sensor icon changes through coordinator updates."""
        await hass.async_block_till_done()
        
        # Just verify the sensor exists and has an icon attribute
        state = hass.states.get("sensor.device123_salt_level")
        assert state is not None
        assert state.attributes.get("icon") is not None

    async def test_available_water_sensor(self, hass, init_integration):
        """Test the available water sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_available_water")
        assert state is not None
        assert state.state == "1000"

    async def test_water_flow_sensor(self, hass, init_integration):
        """Test the water current flow sensor through the state machine.

        Verify the device class and unit of measurement are correct (gal/min).
        """
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_water_current_flow")
        assert state is not None
        # device_class should be volume flow rate
        assert state.attributes.get("device_class") == "volume_flow_rate"
        # unit should match the gallons per minute constant in the integration
        from homeassistant.const import UnitOfVolumeFlowRate
        assert state.attributes.get("unit_of_measurement") == UnitOfVolumeFlowRate.GALLONS_PER_MINUTE

    async def test_water_usage_today_sensor(self, hass, init_integration):
        """Test the today water usage sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_today_water_usage")
        assert state is not None
        assert state.state == "50"

    async def test_water_usage_daily_average_sensor(self, hass, init_integration):
        """Test the daily average water usage sensor through the state machine."""
        await hass.async_block_till_done()
        
        state = hass.states.get("sensor.device123_water_usage_daily_average")
        assert state is not None
        assert state.state == "45"

    async def test_valve_state_sensor(self, hass, init_integration):
        """Test the water shutoff valve state sensor through the state machine."""
        await hass.async_block_till_done()

        state = hass.states.get("sensor.device123_water_shutoff_valve_state")
        assert state is not None
        # The fixture's valve_pos_switch_enum is 0 while the valve status is
        # "open" - reading the rotor position instead would report "close" here
        assert state.state == "open"
        assert state.attributes["manual_override"] is False
        assert state.attributes["error_code"] is None


class TestSensorSetup:
    """Test sensor setup functionality."""

    async def test_async_setup_entry_success(self, hass, mock_config_entry, mock_iqua_softener, mock_iqua_data):
        """Test successful sensor setup."""
        mock_iqua_softener.get_data.return_value = mock_iqua_data
        mock_iqua_softener.has_water_shutoff_valve.return_value = True

        # Mock the coordinator
        coordinator = MagicMock()
        coordinator.data = mock_iqua_data
        coordinator._iqua_softener = mock_iqua_softener

        # Set up hass.data
        hass.data.setdefault("iqua_softener", {})
        hass.data["iqua_softener"][mock_config_entry.entry_id] = {
            "coordinator": coordinator,
            **mock_config_entry.data,
        }

        async_add_entities = MagicMock()

        with patch("custom_components.iqua_softener.sensor._check_water_shutoff_valve_available", return_value=True):
            await async_setup_entry(hass, mock_config_entry, async_add_entities)

            # Verify sensors were added
            assert async_add_entities.called
            call_args = async_add_entities.call_args[0][0]
            assert len(call_args) == 14  # 13 base sensors (including regeneration status, regeneration time remaining, WiFi signal strength, water hardness, and WebSocket connection) + 1 valve sensor

    async def test_check_water_shutoff_valve_available(self, hass, mock_iqua_softener):
        """Test checking water shutoff valve availability."""
        coordinator = MagicMock()
        coordinator._iqua_softener = mock_iqua_softener
        coordinator.hass = hass

        mock_iqua_softener.has_water_shutoff_valve.return_value = True
        result = await _check_water_shutoff_valve_available(coordinator)
        assert result is True

        mock_iqua_softener.has_water_shutoff_valve.return_value = False
        result = await _check_water_shutoff_valve_available(coordinator)
        assert result is False

    async def test_sensor_error_handling(self, hass, init_integration, mock_iqua_data):
        """Test sensor error handling through state machine."""
        await hass.async_block_till_done()
        
        # Verify sensor exists
        state = hass.states.get("sensor.device123_state")
        assert state is not None

class TestWaterShutoffValveState:
    """Test water shutoff valve status parsing and reporting.

    Regression coverage for issue #11, where the sensor read the regeneration
    rotor property `valve_pos_switch_enum` and so never tracked the shutoff
    valve at all.
    """

    @staticmethod
    def _sensor(data):
        """Build the valve sensor and run one update against `data`."""
        coordinator = MagicMock()
        coordinator.data = data
        sensor = IquaSoftenerWaterShutoffValveStateSensor(
            coordinator,
            "DEVICE123",
            SensorEntityDescription(
                key="WATER_SHUTOFF_VALVE_STATE",
                name="Water shutoff valve state",
                icon="mdi:valve",
            ),
        )
        sensor.update(data)
        return sensor

    @pytest.mark.parametrize(
        ("status", "expected_icon"),
        [
            ("open", "mdi:valve-open"),
            ("close", "mdi:valve-closed"),
            ("manual", "mdi:valve"),
            ("error", "mdi:valve"),
            ("not_installed", "mdi:valve"),
        ],
    )
    def test_reports_api_status(self, mock_iqua_data, status, expected_icon):
        """Every API status is reported verbatim, not collapsed to open/closed."""
        data = replace(mock_iqua_data, water_shutoff_valve_status=status)
        sensor = self._sensor(data)

        assert sensor.native_value == status
        assert sensor.icon == expected_icon

    def test_ignores_regeneration_rotor_property(self, mock_iqua_data):
        """valve_pos_switch_enum must not influence the shutoff valve sensor."""
        data = replace(
            mock_iqua_data,
            water_shutoff_valve_status="close",
            water_shutoff_valve_state=0,
            additional_properties={"valve_pos_switch_enum": {"value": 1}},
        )

        assert self._sensor(data).native_value == "close"

    def test_falls_back_to_integer_state(self, mock_iqua_data):
        """Payloads carrying only the on/off integer still resolve."""
        data = replace(
            mock_iqua_data,
            water_shutoff_valve_status=None,
            water_shutoff_valve_state=0,
        )

        assert self._sensor(data).native_value == "close"

    def test_unknown_when_nothing_available(self, mock_iqua_data):
        """No status and no integer means unknown, not a stale open/closed."""
        data = replace(
            mock_iqua_data,
            water_shutoff_valve_status=None,
            water_shutoff_valve_state=None,
        )

        assert self._sensor(data).native_value == "unknown"

    def test_surfaces_error_details(self, mock_iqua_data):
        """error_code and manual_override are exposed as attributes."""
        data = replace(
            mock_iqua_data,
            water_shutoff_valve_status="error",
            water_shutoff_valve_state=None,
            water_shutoff_valve_error_code="both_switch_error",
            water_shutoff_valve_manual_override=True,
        )
        sensor = self._sensor(data)

        assert sensor.extra_state_attributes == {
            "error_code": "both_switch_error",
            "manual_override": True,
        }

    def test_options_match_api_enum(self, mock_iqua_data):
        """The reported options stay in step with the documented API enum."""
        sensor = self._sensor(mock_iqua_data)

        assert sensor.device_class == SensorDeviceClass.ENUM
        assert sensor.options == [
            "open",
            "close",
            "manual",
            "not_installed",
            "unknown",
            "error",
        ]


class TestWebSocketConnectionSensorEnabledDefault:
    """The WebSocket connection sensor is disabled by default on new installs."""

    UNIQUE_ID = "device123_websocket_connection"
    ENTITY_ID = "sensor.device123_websocket_connection"

    async def test_disabled_on_new_install(self, hass, init_integration):
        """A fresh install registers the sensor disabled, with no state."""
        registry = er.async_get(hass)

        entry = registry.async_get(self.ENTITY_ID)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(self.ENTITY_ID) is None

    async def test_existing_install_keeps_it_enabled(
        self, hass, mock_config_entry, mock_iqua_softener
    ):
        """An install already exposing the sensor is left alone."""
        mock_config_entry.add_to_hass(hass)
        registry = er.async_get(hass)
        # Pre-register the sensor the way an existing install would have it
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            self.UNIQUE_ID,
            suggested_object_id="device123_websocket_connection",
            config_entry=mock_config_entry,
        )

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        entry = registry.async_get(self.ENTITY_ID)
        assert entry is not None
        assert entry.disabled_by is None
        assert hass.states.get(self.ENTITY_ID) is not None
