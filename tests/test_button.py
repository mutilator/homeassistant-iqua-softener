"""Tests for the Iqua Softener button platform."""
import pytest
from unittest.mock import MagicMock, patch

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.iqua_softener.const import DOMAIN, CONF_DEVICE_SERIAL_NUMBER, CONF_PRODUCT_SERIAL_NUMBER
from custom_components.iqua_softener.button import (
    async_setup_entry,
    IquaSoftenerRegenerateButton,
)
from custom_components.iqua_softener.vendor.iqua_softener import (
    IquaSoftenerException,
)


class TestButtonEntities:
    """Test button entity functionality."""

    @pytest.mark.asyncio
    async def test_button_initialization(self, hass, mock_coordinator):
        """Test button entity initialization."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")

        assert button._attr_unique_id == "test123_start_regeneration"
        assert button._attr_name == "Start Regeneration"
        assert button._attr_icon == "mdi:reload"
        assert button._device_serial_number == "TEST123"

    @pytest.mark.asyncio
    async def test_button_press(self, hass, mock_coordinator):
        """Test button press action."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")
        button.hass = hass

        # Mock the regenerate_now method
        mock_coordinator._iqua_softener.regenerate_now = MagicMock()

        await button.async_press()

        # Verify regenerate_now was called
        mock_coordinator._iqua_softener.regenerate_now.assert_called_once()
        
        # Verify coordinator refresh was requested
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_button_error_handling(self, hass, mock_coordinator):
        """Test button error handling during press."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")
        button.hass = hass

        # Mock the regenerate_now method to raise an exception
        mock_coordinator._iqua_softener.regenerate_now = MagicMock(
            side_effect=IquaSoftenerException("API Error")
        )

        with pytest.raises(IquaSoftenerException):
            await button.async_press()

    @pytest.mark.asyncio
    async def test_button_available_with_data(self, hass, mock_coordinator, mock_iqua_data):
        """Test button availability when coordinator has data."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")
        button.hass = hass

        # Set coordinator to have successful update and data
        mock_coordinator.last_update_success = True
        mock_coordinator.data = mock_iqua_data

        assert button.available is True

    @pytest.mark.asyncio
    async def test_button_unavailable_without_data(self, hass, mock_coordinator):
        """Test button unavailability when coordinator has no data."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")
        button.hass = hass

        # Set coordinator to have no data
        mock_coordinator.last_update_success = True
        mock_coordinator.data = None

        assert button.available is False

    @pytest.mark.asyncio
    async def test_button_unavailable_on_update_failure(self, hass, mock_coordinator, mock_iqua_data):
        """Test button unavailability on coordinator update failure."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")
        button.hass = hass

        # Set coordinator to have failed update
        mock_coordinator.last_update_success = False
        mock_coordinator.data = mock_iqua_data

        assert button.available is False

    @pytest.mark.asyncio
    async def test_button_device_info(self, hass, mock_coordinator):
        """Test button device info."""
        button = IquaSoftenerRegenerateButton(mock_coordinator, "TEST123")

        device_info = button.device_info
        assert device_info["identifiers"] == {(DOMAIN, "TEST123")}
        assert device_info["name"] == "Iqua Softener TEST123"
        assert device_info["manufacturer"] == "Iqua"
        assert device_info["model"] == "Water Softener"


class TestButtonSetup:
    """Test button platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_success(self, hass, config_entry_data, mock_iqua_data):
        """Test successful button platform setup."""
        from pytest_homeassistant.common import MockConfigEntry
        
        # Create mock coordinator
        mock_coordinator = MagicMock(spec=DataUpdateCoordinator)
        mock_coordinator.data = mock_iqua_data

        # Create a config entry with device_serial_number
        config_data = {**config_entry_data, CONF_DEVICE_SERIAL_NUMBER: "TEST123"}
        test_config_entry = MockConfigEntry(
            domain=DOMAIN,
            data=config_data,
            entry_id="test_button_entry",
        )

        # Set up hass data
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][test_config_entry.entry_id] = {
            CONF_DEVICE_SERIAL_NUMBER: "TEST123",
            "coordinator": mock_coordinator,
        }

        # Mock async_add_entities
        async_add_entities = MagicMock()

        # Call async_setup_entry
        await async_setup_entry(hass, test_config_entry, async_add_entities)

        # Verify button was added
        async_add_entities.assert_called_once()
        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 1
        assert isinstance(buttons[0], IquaSoftenerRegenerateButton)

    @pytest.mark.asyncio
    async def test_async_setup_entry_no_serial_number(self, hass, mock_config_entry):
        """Test button platform setup with no serial number."""
        # Set up hass data without serial numbers
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][mock_config_entry.entry_id] = {}

        # Mock async_add_entities
        async_add_entities = MagicMock()

        # Call async_setup_entry
        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        # Verify no buttons were added
        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_setup_entry_with_product_serial(self, hass, config_entry_data, mock_iqua_data):
        """Test button platform setup with product serial number."""
        from pytest_homeassistant.common import MockConfigEntry
        
        # Create mock coordinator
        mock_coordinator = MagicMock(spec=DataUpdateCoordinator)
        mock_coordinator.data = mock_iqua_data

        # Create config entry with product_serial_number only
        config_data = {k: v for k, v in config_entry_data.items() if k != CONF_DEVICE_SERIAL_NUMBER}
        config_data[CONF_PRODUCT_SERIAL_NUMBER] = "PROD456"
        test_config_entry = MockConfigEntry(
            domain=DOMAIN,
            data=config_data,
            entry_id="test_product_entry",
        )

        # Set up hass data
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][test_config_entry.entry_id] = {
            CONF_PRODUCT_SERIAL_NUMBER: "PROD456",
            "coordinator": mock_coordinator,
        }

        # Mock async_add_entities
        async_add_entities = MagicMock()

        # Call async_setup_entry
        await async_setup_entry(hass, test_config_entry, async_add_entities)

        # Verify button was added with product serial
        async_add_entities.assert_called_once()
        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 1
        assert buttons[0]._device_serial_number == "PROD456"
