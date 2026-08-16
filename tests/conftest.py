"""Test fixtures and utilities for iQua Softener integration tests."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iqua_softener.const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_SERIAL_NUMBER,
    CONF_UPDATE_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
)
from custom_components.iqua_softener.vendor.iqua_softener import (
    IquaSoftener,
    IquaSoftenerData,
    IquaSoftenerState,
    IquaSoftenerVolumeUnit,
)


# Automatically enable custom integrations for all tests
pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Enable custom integrations only for tests that set up Home Assistant."""
    if "hass" in request.fixturenames or "init_integration" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield


@pytest.fixture(autouse=True)
def mock_iqua_softener(mock_iqua_data):
    """Create a mock IquaSoftener instance that's automatically used."""
    # Patch all locations where IquaSoftener is imported
    with patch("custom_components.iqua_softener.sensor.IquaSoftener") as mock_sensor, \
         patch("custom_components.iqua_softener.IquaSoftener") as mock_init:
        
        mock_client = MagicMock()  # Don't use spec - it's too strict
        # Synchronous method that returns data
        mock_client.get_data.return_value = mock_iqua_data
        mock_client.start_websocket.return_value = None  # Synchronous, no return
        mock_client.stop_websocket.return_value = None  # Synchronous, no return
        mock_client.has_water_shutoff_valve.return_value = True
        mock_client.set_water_shutoff_valve_state.return_value = None  # Synchronous method
        mock_client.get_realtime_property.return_value = 1.5
        
        # Both patches should return the same mock instance
        mock_sensor.return_value = mock_client
        mock_init.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_iqua_data():
    """Create mock IquaSoftenerData for testing."""
    from datetime import datetime, timezone

    return IquaSoftenerData(
        timestamp=datetime.now(timezone.utc),
        model="Test Model",
        state=IquaSoftenerState.ONLINE,
        device_date_time=datetime.now(timezone.utc),
        volume_unit=IquaSoftenerVolumeUnit.GALLONS,
        current_water_flow=1.2,
        today_use=50,
        average_daily_use=45,
        total_water_available=1000,
        days_since_last_regeneration=2,
        salt_level=75,
        salt_level_percent=75,
        out_of_salt_estimated_days=30,
        hardness_grains=10,
        water_shutoff_valve_state=1,
        water_shutoff_valve_status="open",
        water_shutoff_valve_error_code=None,
        water_shutoff_valve_manual_override=False,
        enriched_data={
            "regeneration": {
                "regeneration_status": "none",
                "regen_time_rem_secs": 0
            }
        },
        additional_properties={
            # Regeneration rotor position
            "valve_pos_switch_enum": {
                "value": 0
            },
            "treated_water_avail_gals": {
                "converted_value": 1000,
                "converted_units": "Gallons"
            },
            "gallons_used_today": {
                "converted_value": 50,
                "converted_units": "Gallons"
            },
            "avg_daily_use_gals": {
                "converted_value": 45,
                "converted_units": "Gallons"
            }
        },
    )


@pytest.fixture
def config_entry_data():
    """Sample config entry data."""
    return {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "testpass123",
        CONF_DEVICE_SERIAL_NUMBER: "DEVICE123",
        CONF_UPDATE_INTERVAL: 5,
        CONF_ENABLE_WEBSOCKET: True,
    }


@pytest.fixture
def mock_config_entry(config_entry_data):
    """Create a mock config entry using MockConfigEntry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=config_entry_data,
        entry_id="test_entry_id",
        unique_id="DEVICE123",
        title="iQua Device DEVICE123",
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_iqua_softener: MagicMock,
) -> MockConfigEntry:
    """Set up the iQua Softener integration for testing."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def mock_coordinator(mock_iqua_softener, mock_iqua_data):
    """Create a mock coordinator for testing."""
    coordinator = MagicMock()
    coordinator._iqua_softener = mock_iqua_softener
    coordinator.data = mock_iqua_data
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator
    return mock_config_entry
