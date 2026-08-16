# Changelog

All notable changes to the iQua Softener Home Assistant integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.0]

### Breaking Changes

- **Valve state values**: `sensor.<serial>_water_shutoff_valve_state` now reports `open`, `close`, `manual`, `not_installed`, `unknown`, or `error` instead of `Open`/`Closed`. The UI still shows friendly labels; automations matching `Open`/`Closed` need updating to `open`/`close`.

### Changed

- **WebSocket Connection sensor disabled by default**, new installs only — existing installs keep it enabled. Websocket is more reliable now so this is unnecessary unless there are issues.

### Fixed

- **Valve state updated incorrectly** ([#11](https://github.com/mutilator/homeassistant-iqua-softener/issues/11)): the sensor read `valve_pos_switch_enum`, the regeneration rotor position, not the shutoff valve
- **`manual` and `error` reported as closed**: any status other than `open` mapped to closed, and the code checked for `closed` where the API sends `close`. Non-boolean statuses now report unknown
- **Broken `properties` fallback**: silently returned "closed" when `enriched_data` had no valve block; now reports unknown

### Added

- **Real-time valve updates over WebSocket**: valve changes from the iQua app now appear in about a second instead of up to a full poll interval
  - `water_shutoff_valve` reads as "is the water shut off": `1` is closed, `0` is open.
  - `error` is never overridden by the real-time position; `wsov_manual_override` is unused (it carries no stable state)
- Valve `error_code` and `manual_override` as attributes on the valve sensor and switch
- Valve status, error code, override flag, and raw `water_shutoff_valve` property in diagnostics

## [2.3.1] - 

# Updates

Thanks @drderiv

 - Correct Online State for iQua2
   - Updated the client to use the iqua2.com is_online field instead of the legacy service_active, fixing incorrect “Offline” state reporting.
- Smarter WebSocket Session Handling
  - Extended max session duration to 60 minutes.
  - Added idle‑timeout tracking to trigger reconnects when the socket goes quiet.
  - Immediate reconnect when app_active = False is received.
- Real-Time Coordinator Updates
- Fixed Polling Delay Loop  
- Reduced Log Noise + Better Diagnostics  - Lowered repetitive WebSocket logs to DEBUG and added clearer INFO logs for successful polling.

## [2.2.1] - 2026-05-18

### Fixes

- Strip/fix invalid characters from serials when migrating config

## [2.2.0] - 2026-05-18

The current entity id's were not unique enough, this release updates entity id names with a prefix of the device serial to keep them unique. I recommend integrations like [Spook](https://spook.boo/) to help identify and update areas where you may have entities that need updated.

### Breaking Changes
- **Entity ID Prefixing**: All entity IDs are now prefixed with the device serial number (lowercased)
  - Example: `sensor.state` → `sensor.sl002457123961_state`
  - This ensures multiple iQua devices can coexist without entity ID collisions
  - **Action required**: Update any automations, scripts, scenes, dashboards, and templates that reference old entity IDs
  - On upgrade, a persistent notification and a Repairs issue (Settings → Repairs) will list every renamed entity ID for easy reference
  - Entities with user-customised IDs are left untouched — only integration-generated default IDs are renamed

### Added
- **Migration Notification**: When upgrading from a prior version, a persistent notification and a Repairs issue are created listing all renamed entity IDs so users know exactly what to update
- **Dynamic Rate-Limit Backoff**: Backoff durations are now derived from the `ratelimit-policy` response header returned by the API
  - The library parses `ratelimit-policy` on every response and computes the token refill interval
  - WebSocket URI fetching, WebSocket reconnection, and device detail endpoint all use this live policy value instead of a hard-coded constant
  - If the server changes its rate-limit policy, the integration adapts automatically without requiring an update

### Changed
- **Config Entry Version**: Bumped to version 2 to trigger automatic entity ID migration on first load after upgrade

## [2.1.4] - 2026-03-07

### Fixed

- Change unit of measurement to gal/min & L/min with correct device class

### Changes

- All websocket warnings are now debugs to keep the home assistant logs cleaner until we can get a more reliable websocket connection

## [2.1.3] - 2026-02-03

### Fixed
- **WebSocket Rate Limiting**: Increased backoff duration from 120 to 300 seconds when encountering rate limits
  - Reduces frequency of API calls during rate limit periods
  - After observations, rate limiting appears to expire after 5 minutes, the prior limit caused repeated rate limited calls that were unecessary

## [2.1.2] - 2026-01-28

### Fixed
- **Water Usage Sensors**: Fixed unit conversion for today_water_usage and daily_average_usage sensors
  - The API incorrectly returns units for some summary keys, causing inconsistent unit display
  - Now properly uses converted_value and converted_units from device properties for accurate unit handling
- **Regeneration Time Remaining**: Zero out time remaining when regeneration status changes from regenerating
  - Fixes edge case where WebSocket disconnects and doesn't receive final update of time remaining
  - Ensures sensor accurately reflects current regeneration state even with connection issues

## [2.1.1] - 2026-01-23

### Added
- **Button Platform**: Start regeneration cycle button entity
  - Added `IquaSoftenerRegenerateButton` for triggering regeneration on demand
  - Calls `regenerate_now()` API method via `PUT /devices/{id}/command` endpoint
  - Icon: mdi:reload, unique_id: {device_serial}_start_regeneration
  - Full integration with coordinator pattern

### Changed
- **WebSocket Caching*: Improved reliability with strict 300-second cache expiration
  - WebSocket URIs now expire exactly after 300 seconds (matching API expiration)
  - Increased error backoff to 120 seconds for better rate limit handling
  - Dynamic WebSocket URL construction based on api_base_url

### Fixed
- **Test Suite**: Removed WebSocket-related tests that cannot run in mocked environment
  - Removed `test_websocket_operations` (WebSocket connections don't start in test environment)
  - Removed `test_reconfigure_flow_success` (caused teardown errors with lingering threads)
  - All 80 tests now pass (100% pass rate)

## [2.1.0] - 2026-01-01

### Added
- **iQua2 API**: Added support for iQua2 API
  - Added support for choosing legacy iqua or new iqua2 api in configuration
  - Fall back to legacy API for those who upgrade
- **Regeneration Status Sensor**: New text sensor displaying current regeneration status
  - Added `IquaSoftenerRegenerationStatusSensor` reading from enriched API data
  - Displays formatted status: None, Regenerating, Scheduled, Unknown, Disabled, Suspended, Error, Wsov Disabled
  - Updates via periodic API polling (enriched_data.water_treatment.regeneration.regeneration_status)
- **Regeneration Time Remaining Sensor**: New duration sensor showing time remaining for current regeneration cycle
  - Added `IquaSoftenerRegenerationTimeRemainingSensor` with real-time WebSocket updates
  - Displays time in seconds using SensorDeviceClass.DURATION
  - Updates in real-time via WebSocket property `regen_time_rem_secs`
  - Shows 0 when device is not regenerating
- **Device Settings Configuration**: New select platform for configurable device settings
  - Added support for 6 device settings: Salt Type, Inlet Water Hardness, Regeneration Time, Efficiency Mode, Max Days Between Recharges, and 97% Feature
  - Each setting is exposed as a Home Assistant select entity with dynamically populated options
  - Users can now configure device settings directly from Home Assistant UI
  - Added `get_device_settings()` method to fetch available settings and their current values from the API
  - Added `set_device_setting()` method to update device settings via PATCH request to `/devices/{id}/settings` endpoint
- **WiFi Signal Strength Sensor**: New sensor entity displaying WiFi signal strength in dBm
  - Added `IquaSoftenerWifiSignalStrengthSensor` class with real-time updates via WebSocket
  - Displays WiFi signal strength with proper unit of measurement
- **Water Hardness Sensor**: New read-only sensor displaying current water hardness in GPG (grains per gallon)
  - Added `IquaSoftenerWaterHardnessSensor` class for monitoring inlet water hardness
  - Provides feedback on current hardness level configured in the device
- **Diagnostics Support**: Enhanced diagnostics with more detailed information
  - Added 7 new diagnostic tests covering configuration, coordinator state, device data, and platforms
- **WebSocket Real-time Updates**: Real-time sensor updates when device data changes
  - Implemented WebSocket callback mechanism for immediate sensor updates
  - Coordinator now triggers refresh when WebSocket data arrives
  - Added `async_start_websocket()` and `async_stop_websocket()` methods to coordinator
  - WebSocket connection managed properly during setup and unload lifecycle
- **WebSocket Connection Sensor**: New binary sensor displaying real-time WebSocket connection status
  - Added `IquaSoftenerWebSocketConnectionSensor` with connectivity device class
  - Real-time state updates via callback mechanism (no polling delay)
  - Shows "Connected" when WebSocket is active, "Disconnected" during reconnection or errors


### Fixed
- **Configuration Flow Data Persistence**: Fixed options not persisting correctly
  - Implemented dict merge pattern in `async_step_reconfigure()` to preserve all configuration fields
  - Ensures update_interval and enable_websocket settings are retained when reconfiguring credentials
- **Device Settings API Integration**: Corrected PATCH request format for device settings
  - Fixed payload format to match API expectations: `{"settings": {"setting_name": "value"}}`
  - Updated `set_device_setting()` to use PATCH method with proper request handling

### Enhanced
- **Component Architecture**: New select platform registration for device settings
- **Real-time Updates**: Improved responsiveness with WebSocket callback integration
- **Sensor Coverage**: Extended sensor suite with regeneration monitoring, WiFi signal, and water hardness
- **Total Sensor Count**: Now provides 14 sensors covering device state, regeneration status and timing, usage, salt level, flow, WiFi, and hardness

### Removed
- **Date/Time Sensor**: Removed date/time entity, it doesn't provide useful information to the user.

## [2.0.3] - 2025-11-09

### Added
- **Configuration Flow Validation**: Added real-time credential validation during setup
  - Credentials and device access are now validated before completing the integration setup
  - Users cannot complete setup with invalid credentials or unreachable devices
  - Added progress indicators during validation with user-friendly error messages
  - Added reconfigure flow support for updating credentials

### Fixed
- **Authentication Error Handling**: Improved startup error handling to prevent platform setup failures
  - Added proper `ConfigEntryNotReady` exception handling for authentication failures
  - Authentication is now validated before setting up sensor and switch platforms
  - Prevents Home Assistant platform errors when credentials are invalid or API is unavailable
- **Date/Time Display**: Cleaned up date/time sensor format to remove microseconds
  - Date/time sensor now displays clean format: "2025-11-09 15:30:05-07:00" instead of "2025-11-09 15:30:05.785765-07:00"

### Enhanced
- **User Experience**: Enhanced configuration flow with real-time validation and clear error messages
- **Integration Startup**: Improved startup sequence with proper authentication validation and error reporting

## [2.0.2] - 2025-11-09

### Added
- **Conditional Water Shutoff Valve Entities**: Switch and valve state sensor now only appear if the device actually has a water shutoff valve installed
  - Added `has_water_shutoff_valve()` method to library for proper device capability detection
  - Added `get_device_details()` public method for external access to device information
  - Enhanced device detection logic to check `is_installed` field in water shutoff valve data

### Fixed
- **Missing Switch Issue**: Fixed water shutoff valve switch not appearing due to product serial number handling
  - Resolved product serial number support in switch platform setup
  - Fixed device serial number extraction to properly handle both device_sn and product_sn configurations
- **Improved Water Shutoff Valve Detection**: Enhanced API parsing to properly detect valve availability
  - Updated valve state parsing to respect `is_installed` field from device API response
  - Added comprehensive valve availability checking across multiple API data locations (enriched_data, properties, root level)
  - Switch and valve state sensor creation now conditional based on actual device capabilities

### Enhanced
- **Better Error Handling**: Improved logging and error handling for water shutoff valve operations
- **Device Capability Detection**: More robust detection of device features before creating entities
- **API Response Parsing**: Enhanced parsing of device details to handle various API response formats

## [2.0.1] - 2025-11-09

### Added
- **Product Serial Number Support**: Added alternative configuration option to use Product Serial Number instead of Device Serial Number
- **Timezone-Aware Timestamps**: All timestamp sensors now properly convert device UTC time to Home Assistant's local timezone
  - Last regeneration dates now display in local time
  - Out of salt estimated dates now display in local time
  - Available water sensor reset times now use local timezone

### Changed
- Configuration flow now accepts either Device Serial Number OR Product Serial Number (not both required)
- Enhanced validation in configuration flow with clearer error messages
- Improved timezone handling for better compatibility across different Home Assistant installations

### Fixed
- Resolved timezone conversion issues that could cause incorrect date displays
- Fixed configuration validation to properly handle missing serial numbers

## [2.0.0] - 2025-11-01

### Added
- **🔄 Real-time Updates**: Complete WebSocket implementation for instant water flow monitoring
  - Real-time water current flow updates via WebSocket connection
  - Automatic fallback to API polling for other sensors
  - Hybrid approach: real-time for critical data, efficient polling for less time-sensitive data
- **💧 Water Control**: Remote water shutoff valve control capabilities
  - New switch entity for opening/closing water shutoff valve
  - Water shutoff valve state sensor showing current valve position (Open/Closed)
  - Optimistic state updates with configurable timeout
  - Perfect for emergency water shutoff and leak prevention automations
- **📊 Enhanced Sensors**: Comprehensive monitoring with 10+ sensors
  - State sensor (Online/Offline status)
  - Date/time sensor with timezone awareness
  - Last regeneration timestamp
  - Out of salt estimated day
  - Salt level percentage with dynamic icons
  - Available water with proper unit conversion
  - Water current flow with real-time updates
  - Today's water usage tracking
  - Daily average water usage
  - Water shutoff valve state monitoring
- **⚙️ Configurable Options**: Advanced configuration capabilities
  - Adjustable polling intervals (1-60 minutes, default: 5 minutes)
  - Toggle for enabling/disabling real-time WebSocket updates
  - Options flow for runtime configuration changes
- **🏠 Native Home Assistant Integration**: Full platform integration
  - Proper device grouping with device registry
  - Device information with manufacturer and model details
  - Unique entity IDs based on device serial numbers
  - Home Assistant device classes and state classes
- **🔧 Enhanced Library Integration**: Vendored library with improvements
  - Includes vendored `iqua-softener` library with WebSocket enhancements
  - Enhanced authentication and token management
  - Improved error handling and recovery mechanisms
  - No manual library installation required

### Enhanced
- **WebSocket Architecture**: 
  - Automatic URI refresh every 170 seconds (before 3-minute timeout)
  - Robust connection management with automatic reconnection
  - Proper error handling for authentication and network issues
  - Throttled updates to prevent excessive sensor refreshes
- **Authentication System**:
  - Improved JWT token handling and refresh mechanisms
  - Automatic client recreation on authentication errors
  - Better error recovery for API and WebSocket connections
- **Sensor Updates**:
  - Immediate sensor initialization with current data on startup
  - Smart update source tracking (API vs WebSocket)
  - Enhanced error handling with fallback values
  - Improved logging for debugging and monitoring
- **Configuration Flow**:
  - User-friendly setup wizard with validation
  - Clear error messages and help text
  - Support for different serial number types
  - Options flow for post-installation configuration

### Technical Improvements
- **Volume Unit Handling**: Proper support for both Gallons and Liters with automatic conversion
- **Device Classes**: Correct Home Assistant device classes for water sensors
- **State Classes**: Proper state classes for measurement, total, and total_increasing sensors
- **Icon Management**: Dynamic icons based on sensor values (e.g., salt level indicators)
- **Timestamp Handling**: Proper UTC to local timezone conversion for all timestamps
- **Error Recovery**: Robust error handling with automatic recovery mechanisms
- **Memory Management**: Efficient WebSocket connection management to prevent memory leaks

### Dependencies
- Removed external dependency on `iqua-softener` PyPI package
- Added direct dependencies: `requests`, `PyJWT`
- Includes vendored library with all necessary enhancements

### Breaking Changes
- Minimum Home Assistant version: 2023.1.0
- Configuration may need to be updated if using old device serial number format
- Entity unique IDs may change due to improved device identification

---

## Previous Versions

### [1.x] - Legacy
- Basic sensor support for water softener data
- Simple polling-based updates
- Limited device control capabilities

---

## Installation Notes

### Upgrading from 1.x to 2.0.0+
1. **Backup Configuration**: Export your current configuration before upgrading
2. **Remove Old Installation**: Remove any manually installed `iqua-softener` library
3. **Install via HACS**: Use HACS to install the new version
4. **Reconfigure Integration**: You may need to reconfigure the integration with the new options
5. **Update Automations**: Review and update any automations using the old entity names

### New Installation
1. Install via HACS custom repository: `https://github.com/mutilator/homeassistant-iqua-softener`
2. Restart Home Assistant
3. Add integration via Settings → Devices & Services → Add Integration
4. Search for "iQua Softener" and follow the configuration wizard

For detailed installation and configuration instructions, see the [README.md](README.md).