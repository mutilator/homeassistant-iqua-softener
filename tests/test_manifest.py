"""Test the iQua Softener integration manifest and basic functionality."""
import json
import pytest
from pathlib import Path

from custom_components.iqua_softener.const import DOMAIN
from homeassistant.const import UnitOfVolumeFlowRate

def load_manifest():
    """Load the manifest from the JSON file."""
    manifest_path = Path(__file__).parent.parent / "custom_components" / "iqua_softener" / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestManifest:
    """Test the integration manifest."""

    def test_manifest_structure(self):
        """Test that the manifest has required fields."""
        manifest = load_manifest()
        assert manifest["domain"] == DOMAIN
        assert manifest["name"] == "iQua Softener"
        assert manifest["version"] is not None
        assert manifest["config_flow"] is True
        assert "iot_class" in manifest
        assert manifest["iot_class"] == "cloud_polling"

    def test_manifest_dependencies(self):
        """Test manifest dependencies."""
        manifest = load_manifest()
        assert "dependencies" in manifest
        # Should have no external dependencies as per the vendored library approach
        assert len(manifest["dependencies"]) == 0

    def test_manifest_requirements(self):
        """Test manifest requirements."""
        manifest = load_manifest()
        assert "requirements" in manifest
        # requests and PyJWT ship with Home Assistant, so hassfest rejects
        # listing them; the vendored library needs no other packages
        assert manifest["requirements"] == []


class TestConstants:
    """Test the constants module."""

    def test_domain_constant(self):
        """Test domain constant."""
        assert DOMAIN == "iqua_softener"

    def test_config_constants(self):
        """Test configuration constants."""
        from custom_components.iqua_softener.const import (
            CONF_USERNAME,
            CONF_PASSWORD,
            CONF_DEVICE_SERIAL_NUMBER,
            CONF_PRODUCT_SERIAL_NUMBER,
            CONF_UPDATE_INTERVAL,
            CONF_ENABLE_WEBSOCKET,
            DEFAULT_UPDATE_INTERVAL,
            DEFAULT_ENABLE_WEBSOCKET,
            SWITCH_OPTIMISTIC_TIMEOUT,
        )

        assert CONF_USERNAME == "username"
        assert CONF_PASSWORD == "password"
        assert CONF_DEVICE_SERIAL_NUMBER == "device_sn"
        assert CONF_PRODUCT_SERIAL_NUMBER == "product_sn"
        assert CONF_UPDATE_INTERVAL == "update_interval"
        assert CONF_ENABLE_WEBSOCKET == "enable_websocket"
        assert DEFAULT_UPDATE_INTERVAL == 5
        assert DEFAULT_ENABLE_WEBSOCKET is True
        assert SWITCH_OPTIMISTIC_TIMEOUT == 10

    def test_flow_rate_enum_import(self):
        """Ensure the home assistant flow-rate enum is available."""
        from homeassistant.const import UnitOfVolumeFlowRate

        # Basic sanity check of enum members used by integration
        assert UnitOfVolumeFlowRate.LITERS_PER_MINUTE
        assert UnitOfVolumeFlowRate.GALLONS_PER_MINUTE


class TestImportStructure:
    """Test that all modules can be imported."""

    def test_import_main_module(self):
        """Test importing the main module."""
        import custom_components.iqua_softener
        assert custom_components.iqua_softener is not None

    def test_import_config_flow(self):
        """Test importing the config flow module."""
        from custom_components.iqua_softener import config_flow
        assert config_flow is not None

    def test_import_sensor(self):
        """Test importing the sensor module."""
        from custom_components.iqua_softener import sensor
        assert sensor is not None

    def test_import_switch(self):
        """Test importing the switch module."""
        from custom_components.iqua_softener import switch
        assert switch is not None

    def test_import_const(self):
        """Test importing the constants module."""
        from custom_components.iqua_softener import const
        assert const is not None

    def test_import_vendor_library(self):
        """Test importing the vendored library."""
        from custom_components.iqua_softener.vendor import iqua_softener
        assert iqua_softener is not None

        # Test specific imports
        from custom_components.iqua_softener.vendor.iqua_softener import (
            IquaSoftener,
            IquaSoftenerData,
            IquaSoftenerException,
        )
        assert IquaSoftener is not None
        assert IquaSoftenerData is not None
        assert IquaSoftenerException is not None