"""Resin state parsing, conditional creation, and real HA lifecycle regressions."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.iqua_softener.binary_sensor import (
    _resin_alert_value,
    async_setup_entry,
)
from custom_components.iqua_softener.const import (
    CONF_DEVICE_SERIAL_NUMBER,
    CONF_ENABLE_WEBSOCKET,
    CONF_PRODUCT_SERIAL_NUMBER,
    DOMAIN,
)
from custom_components.iqua_softener.vendor.iqua_softener import IquaSoftenerState

ENTITY_ID = "binary_sensor.device123_resin_maintenance_alert"
MISSING = object()


def snapshot(data, *, enriched=MISSING, raw=MISSING):
    """Synthetic snapshots preserve unrelated sensors' existing fixture data."""
    treatment = dict(data.enriched_data or {})
    props = dict(data.additional_properties or {})
    treatment.pop("water_treatment_status", None)
    props.pop("resin_alert", None)
    if enriched is not MISSING:
        treatment["water_treatment_status"] = {"resin_alert": enriched}
    if raw is not MISSING:
        props["resin_alert"] = {"value": raw}
    return replace(data, enriched_data=treatment, additional_properties=props)


READINGS = [
    (True, MISSING, True),
    (False, MISSING, False),
    (MISSING, 1, True),
    (MISSING, 0, False),
    (True, 1, True),
    (False, 0, False),
    (False, 1, False),  # Valid enriched data has priority, including false.
    (True, 0, True),
    (None, 1, True),
    ("invalid", 0, False),
    (1, 0, False),  # Enriched integers are invalid; use the valid raw fallback.
    (MISSING, MISSING, None),
    (None, None, None),
    ("false", "0", None),
    (0, False, None),  # Raw booleans are not the verified integer representation.
    (1, True, None),
    ([], {}, None),
    ({}, [], None),
    (MISSING, 2, None),
    (MISSING, -1, None),
    (MISSING, 0.0, None),
    (MISSING, 1.0, None),
    (MISSING, float("nan"), None),
    (MISSING, float("inf"), None),
]


@pytest.mark.parametrize(("enriched", "raw", "expected"), READINGS)
async def test_readings_and_conditional_creation(
    hass, mock_iqua_data, mock_iqua_softener, enriched, raw, expected
):
    """Create only for strict valid states; never request extra client data."""
    data = snapshot(mock_iqua_data, enriched=enriched, raw=raw)
    assert _resin_alert_value(data) is expected
    coordinator = MagicMock(data=data, last_update_success=True)
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    hass.data[DOMAIN] = {
        entry.entry_id: {
            CONF_DEVICE_SERIAL_NUMBER: "DEVICE123",
            "coordinator": coordinator,
        }
    }
    add = MagicMock()
    mock_iqua_softener.reset_mock()
    await async_setup_entry(hass, entry, add)
    if expected is None:
        add.assert_not_called()
    else:
        entity = add.call_args.args[0][0]
        assert entity.is_on is expected
        assert entity.available
        assert entity.unique_id == "device123_resin_alert"
        assert entity.device_class == BinarySensorDeviceClass.PROBLEM
        assert entity.device_info["identifiers"] == {(DOMAIN, "DEVICE123")}
        assert not entity.should_poll
        add.assert_called_once()
    assert not mock_iqua_softener.mock_calls


@pytest.mark.parametrize(
    ("enriched", "props"),
    [
        (None, None),
        ([], []),
        ({}, {}),
        ({"water_treatment_status": None}, {"resin_alert": None}),
        ({"water_treatment_status": []}, {"resin_alert": []}),
        ({"water_treatment_status": {}}, {"resin_alert": {}}),
    ],
)
def test_invalid_containers(mock_iqua_data, enriched, props):
    """Malformed parent objects also remain unknown rather than healthy."""
    assert (
        _resin_alert_value(
            replace(mock_iqua_data, enriched_data=enriched, additional_properties=props)
        )
        is None
    )
    assert _resin_alert_value(None) is None


@pytest.mark.parametrize("serial", [None, "PRODUCT123"])
async def test_serial_selection(hass, mock_iqua_data, serial):
    """Follow upstream's product-serial fallback and require an identity."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    coordinator = MagicMock(data=snapshot(mock_iqua_data, raw=0))
    hass.data[DOMAIN] = {
        entry.entry_id: {
            CONF_PRODUCT_SERIAL_NUMBER: serial,
            "coordinator": coordinator,
        }
    }
    add = MagicMock()
    await async_setup_entry(hass, entry, add)
    if serial:
        assert add.call_args.args[0][0].unique_id == "product123_resin_alert"
    else:
        add.assert_not_called()


async def setup(hass, config_entry_data):
    """Use real HA platform setup with only the cloud client mocked."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**config_entry_data, CONF_ENABLE_WEBSOCKET: False},
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]["coordinator"]


async def test_states_availability_recovery_and_no_requests(
    hass, config_entry_data, mock_iqua_data, mock_iqua_softener
):
    """HA receives on/off/unavailable correctly, without refreshing the client."""
    clear = snapshot(mock_iqua_data, enriched=False, raw=0)
    mock_iqua_softener.get_data.return_value = clear
    entry, coordinator = await setup(hass, config_entry_data)
    assert hass.states.get(ENTITY_ID).state == "off"
    assert hass.states.get(ENTITY_ID).attributes["device_class"] == "problem"
    assert (
        hass.states.get(ENTITY_ID)
        .attributes["friendly_name"]
        .endswith("Resin maintenance alert")
    )
    assert hass.states.get(ENTITY_ID).attributes["icon"] == "mdi:water-alert"
    mock_iqua_softener.get_data.assert_called_once_with()
    mock_iqua_softener.reset_mock()
    for data, expected in [
        (snapshot(clear, enriched=True, raw=1), "on"),
        (snapshot(clear, raw=0), "off"),
        (snapshot(clear), STATE_UNAVAILABLE),
        (snapshot(clear, enriched=None, raw="0"), STATE_UNAVAILABLE),
        (snapshot(clear, raw=1), "on"),
        (replace(clear, state=IquaSoftenerState.OFFLINE), STATE_UNAVAILABLE),
        (clear, "off"),
        (None, STATE_UNAVAILABLE),
        (clear, "off"),
    ]:
        coordinator.async_set_updated_data(data)
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY_ID).state == expected
    coordinator.async_set_update_error(UpdateFailed("Synthetic fetch failure"))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    coordinator.async_set_updated_data(clear)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "off"
    mock_iqua_softener.get_data.assert_not_called()
    assert all(
        call[0] == "get_realtime_property" for call in mock_iqua_softener.mock_calls
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_late_reading_requires_reload_and_unloads_cleanly(
    hass, config_entry_data, mock_iqua_data, mock_iqua_softener
):
    """Match setup-time valve discovery; reload adds once and unload detaches."""
    entry, coordinator = await setup(hass, config_entry_data)
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY_ID) is None
    data = snapshot(mock_iqua_data, raw=0)
    mock_iqua_softener.get_data.return_value = data
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()
    assert registry.async_get(ENTITY_ID) is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "off"
    registered_id = registry.async_get(ENTITY_ID).id
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(ENTITY_ID).id == registered_id
    # Old listeners must be removed after a reload.
    assert not coordinator._listeners
    current = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not current._listeners
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


@pytest.mark.parametrize("disabled", [False, True])
async def test_registry_compatibility(
    hass, config_entry_data, mock_iqua_data, mock_iqua_softener, disabled
):
    """Preserve customized IDs, user disablement, and existing sensor identity."""
    mock_iqua_softener.get_data.return_value = snapshot(mock_iqua_data, raw=0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**config_entry_data, CONF_ENABLE_WEBSOCKET: False},
        version=3,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "device123_salt_level",
        config_entry=entry,
        suggested_object_id="custom_salt",
    )
    alert = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "device123_resin_alert",
        config_entry=entry,
        suggested_object_id="custom_resin",
        disabled_by=er.RegistryEntryDisabler.USER if disabled else None,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id).id == old.id
    assert hass.states.get(old.entity_id).state == "75"
    assert registry.async_get(alert.entity_id).id == alert.id
    assert registry.async_get(alert.entity_id).disabled_by == alert.disabled_by
    assert (
        registry.async_get(alert.entity_id).device_id
        == registry.async_get(old.entity_id).device_id
    )
    assert hass.states.get(ENTITY_ID) is None
    assert (hass.states.get(alert.entity_id) is None) == disabled
    assert entry.version == 3
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_no_initial_data(hass, mock_iqua_softener):
    """No snapshot means no entity, without a platform-specific refresh."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    hass.data[DOMAIN] = {
        entry.entry_id: {
            CONF_DEVICE_SERIAL_NUMBER: "DEVICE123",
            "coordinator": MagicMock(data=None),
        }
    }
    add = MagicMock()
    mock_iqua_softener.reset_mock()
    await async_setup_entry(hass, entry, add)
    add.assert_not_called()
    assert not mock_iqua_softener.mock_calls
