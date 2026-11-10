import logging

from homeassistant import config_entries, core
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import slugify
from .vendor.iqua_softener import IquaSoftener, IquaSoftenerException

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_SERIAL_NUMBER,
    CONF_PRODUCT_SERIAL_NUMBER,
    CONF_UPDATE_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_API_TYPE,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_API_TYPE,
    API_URLS,
)
from .sensor import IquaSoftenerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    if entry.options:
        hass_data.update(entry.options)

    # Create shared coordinator
    update_interval_minutes = hass_data.get(
        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
    )
    # Ensure update_interval is an integer (in minutes) and convert to seconds for timedelta
    update_interval_minutes = int(update_interval_minutes) if update_interval_minutes else DEFAULT_UPDATE_INTERVAL
    update_interval_seconds = update_interval_minutes * 60
    enable_websocket = hass_data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)
    _LOGGER.info(
        "Creating coordinator with update interval: %d minutes (%d seconds), WebSocket: %s",
        update_interval_minutes,
        update_interval_seconds,
        enable_websocket,
    )
    # Extract serial numbers from config
    device_sn = hass_data.get(CONF_DEVICE_SERIAL_NUMBER)
    product_sn = hass_data.get(CONF_PRODUCT_SERIAL_NUMBER)
    
    # Get selected API type and corresponding URL
    # Backward compatibility: If api_type is not in config (existing installations),
    # default to legacy iQua API to maintain compatibility with existing setups
    api_type = hass_data.get(CONF_API_TYPE, DEFAULT_API_TYPE)
    api_url = API_URLS.get(api_type, API_URLS[DEFAULT_API_TYPE])
    
    _LOGGER.info("Creating IquaSoftener with device_sn=%s, product_sn=%s, api_type=%s, api_url=%s", 
                 device_sn, product_sn, api_type, api_url)
    
    # Create coordinator (authentication already validated in config flow)
    coordinator = IquaSoftenerCoordinator(
        hass,
        IquaSoftener(
            hass_data[CONF_USERNAME],
            hass_data[CONF_PASSWORD],
            device_serial_number=device_sn,
            product_serial_number=product_sn,
            api_base_url=api_url,
            enable_websocket=enable_websocket,  # Let the library handle WebSocket
        ),
        update_interval_seconds,
        enable_websocket,
        hass_data,  # Pass config data for URL configuration
    )

    # Perform initial data fetch for immediate availability
    try:
        _LOGGER.info("Performing initial data fetch...")
        await coordinator.async_config_entry_first_refresh()
        
        if coordinator.data is None:
            _LOGGER.warning("Initial data fetch returned no data, but continuing setup")
        else:
            _LOGGER.info("Initial data fetch successful")
            
    except Exception as err:
        _LOGGER.warning("Initial data fetch failed, but continuing setup: %s", err)
        # Don't fail the entire setup if initial fetch fails - the coordinator will retry

    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass_data["coordinator"] = coordinator
    hass.data[DOMAIN][entry.entry_id] = hass_data

    # WebSocket will be started automatically by coordinator after first successful data fetch
    # This prevents duplicate WebSocket connections and ensures proper initialization order
    if enable_websocket:
        _LOGGER.info("WebSocket is enabled - will start automatically after first data fetch")
    else:
        _LOGGER.info("WebSocket is disabled in configuration")

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "switch", "select", "button"])
    return True


async def options_update_listener(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    _LOGGER.info("Options updated, reloading integration")
    # Stop WebSocket before reload
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_stop_websocket()

    await hass.config_entries.async_reload(config_entry.entry_id)


def _notify_entity_id_migration(
    hass: core.HomeAssistant, renamed: list[tuple[str, str]]
) -> None:
    """Create a persistent notification and a Repairs issue listing renamed entity IDs.

    Called once after all entity-registry renames are complete so the user knows
    which old entity IDs to search for in automations, scripts, dashboards, etc.
    """
    lines = "\n".join(f"- `{old}` → `{new}`" for old, new in renamed)

    message = (
        "iQua Softener entity IDs have been updated to include the device serial "
        "number so that multiple devices can coexist.\n\n"
        f"{lines}\n\n"
        "Please check your automations, scripts, scenes, dashboards, and "
        "templates for references to the old entity IDs and update them manually."
    )

    persistent_notification.async_create(
        hass,
        message,
        title="iQua Softener — entity IDs renamed",
        notification_id=f"{DOMAIN}_entity_id_migration",
    )

    ir.async_create_issue(
        hass,
        DOMAIN,
        "entity_id_migration",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        learn_more_url=(
            "https://github.com/mutilator/homeassistant-iqua-softener/blob/master/CHANGELOG.md"
        ),
        translation_key="entity_id_migration",
        translation_placeholders={"entity_list": lines},
    )

    _LOGGER.warning(
        "iQua Softener: %d entity ID(s) renamed. "
        "Check automations, dashboards, and templates for old references. "
        "See the Repairs panel or the persistent notification for the full list.",
        len(renamed),
    )


async def async_migrate_entry(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
) -> bool:
    """Migrate old config entry to new version.

    Version 1 → 2: Prefix entity IDs with the device serial number so that
    multiple devices can coexist without entity-ID collisions.
    Only entities still using the integration-generated default ID are renamed;
    user-customised IDs are left untouched.
    Version 2 → 3: Migrate WebSocket connection entity from binary_sensor
    domain to sensor domain.
    """
    _LOGGER.info(
        "Migrating iQua Softener config entry from version %s", config_entry.version
    )

    if config_entry.version < 2:
        data = dict(config_entry.data)
        if config_entry.options:
            data.update(config_entry.options)

        device_sn = data.get(CONF_DEVICE_SERIAL_NUMBER) or data.get(
            CONF_PRODUCT_SERIAL_NUMBER
        )
        if not device_sn:
            _LOGGER.error(
                "Cannot migrate iQua Softener entry: no device serial number in config"
            )
            return False

        serial_lower = slugify(device_sn)
        entity_registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )

        renamed: list[tuple[str, str]] = []

        for entry in entries:
            if not entry.original_name:
                continue

            # Compute what the old auto-generated entity_id should have been.
            expected_old_id = f"{entry.domain}.{slugify(entry.original_name)}"

            if entry.entity_id != expected_old_id:
                # User has customised this entity_id – leave it alone.
                _LOGGER.debug(
                    "Skipping migration for customised entity %s", entry.entity_id
                )
                continue

            # Build the new entity_id with the serial prefix.
            old_key = entry.entity_id[len(entry.domain) + 1:]  # strip "domain."
            new_entity_id = f"{entry.domain}.{serial_lower}_{old_key}"

            if entity_registry.async_get(new_entity_id) is not None:
                _LOGGER.warning(
                    "Target entity_id %s already exists, skipping migration for %s",
                    new_entity_id,
                    entry.entity_id,
                )
                continue

            entity_registry.async_update_entity(
                entry.entity_id, new_entity_id=new_entity_id
            )
            _LOGGER.info(
                "Migrated entity_id %s → %s", entry.entity_id, new_entity_id
            )
            renamed.append((entry.entity_id, new_entity_id))

        if renamed:
            _notify_entity_id_migration(hass, renamed)

        hass.config_entries.async_update_entry(config_entry, version=2)
        _LOGGER.info("iQua Softener config entry migration to version 2 complete")

    if config_entry.version < 3:
        data = dict(config_entry.data)
        if config_entry.options:
            data.update(config_entry.options)

        device_sn = data.get(CONF_DEVICE_SERIAL_NUMBER) or data.get(
            CONF_PRODUCT_SERIAL_NUMBER
        )
        if not device_sn:
            _LOGGER.error(
                "Cannot migrate iQua Softener entry to version 3: no device serial number in config"
            )
            return False

        websocket_unique_id = f"{device_sn}_websocket_connection".lower()
        entity_registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )

        for entry in entries:
            if entry.domain != "binary_sensor":
                continue
            if entry.unique_id != websocket_unique_id:
                continue

            old_entity_id = entry.entity_id
            object_id = old_entity_id.split(".", 1)[1]
            new_entity_id = f"sensor.{object_id}"

            if entity_registry.async_get(new_entity_id) is not None:
                _LOGGER.warning(
                    "Target entity_id %s already exists, skipping WebSocket migration for %s",
                    new_entity_id,
                    old_entity_id,
                )
                continue

            entity_registry.async_update_entity(
                old_entity_id, new_entity_id=new_entity_id
            )
            _LOGGER.info(
                "Migrated WebSocket entity_id %s → %s", old_entity_id, new_entity_id
            )

        hass.config_entries.async_update_entry(config_entry, version=3)
        _LOGGER.info("iQua Softener config entry migration to version 3 complete")

    return True


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry with proper cleanup.
    
    Performs graceful shutdown:
    - Stops WebSocket connection if active
    - Cancels pending coordinator tasks
    - Removes options update listener
    - Unloads all platforms
    - Cleans up stored data
    """
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    
    if entry_data:
        # Stop the WebSocket connection
        coordinator = entry_data.get("coordinator")
        if coordinator:
            try:
                await coordinator.async_stop_websocket()
            except Exception as err:
                _LOGGER.warning("Error stopping WebSocket: %s", err)
        
        # Remove options update listener
        unsub_listener = entry_data.get("unsub_options_update_listener")
        if unsub_listener:
            unsub_listener()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "switch", "select", "button"]
    )

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
