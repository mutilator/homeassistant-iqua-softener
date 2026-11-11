# iQua app supported water softeners integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/mutilator/homeassistant-iqua-softener.svg)](https://github.com/mutilator/homeassistant-iqua-softener/releases)

`iqua_softener` is a _custom component_ for [Home Assistant](https://www.home-assistant.io/). The integration allows you to pull data for you iQua app supported water softener from Ecowater company server.

## Features

- **🔄 Real-time Updates**: WebSocket support for instant water flow monitoring
- **💧 Water Control**: Remote water shutoff valve control for emergency situations
- **📊 Comprehensive Monitoring**: 11 sensors covering all aspects of your water softener
- **⚙️ Configurable**: Adjustable polling intervals and real-time update settings
- **⚡ Device Control**: Button entity for starting regeneration cycles on demand
- **🏠 Native Integration**: Full Home Assistant integration with device grouping
- **🔧 Automation Ready**: Perfect for leak detection and water usage automations

It will create eleven sensors with both periodic updates and real-time WebSocket data (default polling interval: 10 minutes, with real-time flow updates):
- State - whether the softener is connected to Ecowater server
- Regeneration Status - current regeneration status (None, Regenerating, Scheduled, etc.)
- Regeneration Time Remaining - time remaining for current regeneration cycle in seconds
- Last regeneration - the day of last regeneration
- Out of salt estimated day - the day on which the end of salt is predicted
- Salt level - salt level load in percentage
- Today water usage - water used today
- Water current flow - current flow of water
- Water usage daily average - computed average by softener of daily usage
- Available water - water available to use before next regeneration
- Water shutoff valve state - current state of the water shutoff valve (Open/Closed)

It will also create one switch:
- Water shutoff valve - allows you to remotely open/close the water shutoff valve

It will also create one button:
- Start Regeneration - triggers an immediate regeneration cycle

It will also create select entities for device configuration:
- Regeneration Time - set the time when regeneration occurs
- Salt Type - choose between NaCl (sodium) and KCl (potassium)
- Efficiency Mode - select Salt Efficient or Auto Adjusting mode
- Max Days Between Recharges - set maximum days between regeneration cycles
- Inlet Hardness - set incoming water hardness level

The units displayed are set in the application settings.

![Homeassistant controls dialog](controls.png)

![Homeassistant sensor dialog](sensor.png)

## Resin Maintenance Alert

A **Resin maintenance alert** problem binary sensor is created at setup when the
coordinator contains an enriched `water_treatment_status.resin_alert` boolean or
a raw `resin_alert` integer of 0 or 1. A readable value indicates available API
data; it does not guarantee physical feature support on every model. No model
allowlist is used. Reload the integration if the field first appears after setup.

## Real-Time Data Updates

The integration supports real-time data updates via WebSocket connection for select sensors:

- **Water Current Flow**: Updates in real-time as water flow changes
- **WebSocket Connection**: Sensor showing real-time connection status
- **Other sensors**: Continue to use the configured polling interval for updates

This provides the best of both worlds:
- **Real-time responsiveness** for critical flow monitoring
- **Efficient polling** for less time-sensitive data like salt levels and regeneration status

The WebSocket connection is automatically managed by Home Assistant and will reconnect if the connection is lost.

### WebSocket Behavior and Optimization

**Important Note about Water Flow Data**: The iQua API has specific behavior regarding real-time flow data:

- **Flow Data Timeout**: `current_water_flow_gpm` is only transmitted during the **first 3 minutes** of a WebSocket connection
- **Automatic Reconnection**: To ensure continuous flow monitoring, the integration automatically reconnects every **170 seconds** (2 minutes 50 seconds)
- **Connection Stability**: WebSocket connections remain active after 3 minutes, but they stop sending flow updates
- **Proactive Reconnection**: The 170-second interval keeps the connection fresh and ensures uninterrupted flow data

**API Rate Limiting**: The iQua API implements rate limiting on certain endpoints:

- **Rate-Limited Endpoint**: `/devices/{device_id}/live` (used to obtain WebSocket URIs)
- **URI Caching**: The integration caches WebSocket URIs for 4 minutes to reduce API calls
- **Cache Benefits**: Reduces API calls to the `/live` endpoint by approximately 50% (~10 calls/hour vs ~20 calls/hour)
- **Stale URI Fallback**: If the API returns a rate limit error (429), the integration will attempt to use a previously cached URI
- **Exponential Backoff**: On repeated failures, the integration implements exponential backoff (60s to 30 minutes) to prevent API exhaustion

These optimizations ensure reliable real-time water flow monitoring while respecting API rate limits and maintaining stable connections.

## Water Shutoff Valve Control

The integration now includes remote control of the water shutoff valve through both a sensor (showing current state) and a switch (for control). This allows you to:

- Monitor the current state of your water shutoff valve
- Remotely shut off water supply in case of emergency
- Integrate valve control into Home Assistant automations

**Important Safety Note:** The water shutoff valve control is intended for emergency use and maintenance purposes. Always ensure you understand the implications of shutting off your water supply before using this feature.

### Example Automations

Here are some example automations you can create:

**Emergency Water Shutoff:**
```yaml
alias: "Emergency Water Shutoff"
trigger:
  - platform: state
    entity_id: binary_sensor.water_leak_detector
    to: "on"
action:
  - service: switch.turn_off
    target:
      entity_id: switch.iqua_softener_water_shutoff_valve
  - service: notify.mobile_app_your_phone
    data:
      message: "Water leak detected! Water supply has been shut off."
```

**Water Usage Alert with Auto Shutoff:**
```yaml
alias: "High Water Usage Alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.iqua_softener_water_current_flow
    above: 50  # Adjust threshold as needed
    for:
      minutes: 30
action:
  - service: switch.turn_off
    target:
      entity_id: switch.iqua_softener_water_shutoff_valve
  - service: notify.mobile_app_your_phone
    data:
      message: "Unusually high water flow detected for 30 minutes. Water supply has been shut off as a precaution."
```

## Installation

### Method 1: HACS (Recommended)

**Note: This integration includes a vendored copy of the required library, so no additional manual installation is needed.**

1. **Install HACS** if you haven't already:
   - Follow the [HACS installation guide](https://hacs.xyz/docs/setup/download)

2. **Add this repository to HACS**:
   - Go to HACS in your Home Assistant
   - Click on "Integrations"
   - Click the three dots menu (⋮) in the top right
   - Select "Custom repositories"
   - Add repository URL: `https://github.com/mutilator/homeassistant-iqua-softener`
   - Select category: "Integration"
   - Click "Add"

3. **Install the integration**:
   - Search for "iQua Softener" in HACS
   - Click "Download"
   - Restart Home Assistant

### Method 2: Manual Installation

Copy the `custom_components/iqua_softener` folder into your Home Assistant `config/custom_components` directory.

**Directory structure should look like:**
```
config/
  custom_components/
    iqua_softener/
      __init__.py
      config_flow.py
      const.py
      manifest.json
      sensor.py
      switch.py
      strings.json
      vendor/          # Vendored iqua-softener library
        iqua_softener/
      translations/
        en.json
```

After installation (either method), restart Home Assistant.

### About the Vendored Library

This integration currently includes a vendored copy of the `iqua-softener` library with enhanced WebSocket and authentication features. This approach:

- **Eliminates manual installation** - No need to manually install the library
- **Ensures compatibility** - The exact version with required features is included
- **Simplifies deployment** - Users only need to install the integration itself

The vendored library will be removed once the upstream changes are merged and published to PyPI.

## Prerequisites

- Home Assistant 2023.1.0 or newer
- Active iQua account with water softener registered
- Network connectivity for your Home Assistant instance

## Configuration
To add an iQua water softener to Home Assistant:

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration**
3. Search for and select **iQua Softener**
4. Enter your account and update settings:
   - **API Type** - select which API to use:
     - **iQua** (default) - for legacy Ecowater devices and existing user accounts
     - **iQua2** - for newer Ecowater devices and new user accounts created after the migration
   - **Username** - username for the iQua application
   - **Password** - password for the iQua application
   - **Update Interval (minutes)** - how often to poll the iQua servers for updated data (default: 5 minutes, range: 1-60 minutes)
   - **Enable Real-time Updates** - enable WebSocket connection for real-time data updates (default: enabled)
5. After your credentials are validated, the integration queries the iQua API for devices on your account.
6. Select the water softener you want to add from the discovered device list.

You no longer need to manually enter a device serial number or product serial number during setup. The selected device's serial information is stored automatically and is still used internally for unique device and entity IDs.

If your account has multiple water softeners, repeat the setup flow and select a different device each time.

### API Type Selection

The integration supports both the legacy **iQua API** and the newer **iQua2 API**. Both APIs are functionally identical with the same endpoints, data structure, and authentication methods - they only differ in their user and device registrations:

- **iQua API** (`api.myiquaapp.com`):
  - For existing Ecowater devices
  - For accounts created before the iQua2 migration
  - Default selection for backward compatibility
  
- **iQua2 API** (`api.iqua2.com`):
  - For newer Ecowater devices  
  - For accounts created after the iQua2 migration
  - Same functionality as iQua API, just a different user/device database

**Important Notes:**
- Choose the API that matches where your account and device are registered
- If you're unsure, try the default iQua API first - if authentication fails, switch to iQua2
- Existing installations will automatically continue using the iQua API when upgraded
- You can switch between APIs at any time using the Reconfigure option; after changing credentials or API type, the integration will rediscover devices and ask which device to use

The API selector was implemented because both APIs are architecturally identical - they use the same authentication mechanisms, return the same data structures, and support the same WebSocket connections. The only difference is which user accounts and device registrations they contain.

### Configuration Options

After initial setup, you can modify settings by:
1. Go to **Settings → Devices & Services**
2. Find your iQua Softener integration
3. Click **"Configure"** or the options button (⋯)
4. Adjust the update interval or toggle real-time updates

To update credentials, change API type, or select a different softener from the account, use the integration's **Reconfigure** flow. Reconfigure will ask for credentials, query the API again, and show the discovered device picker.

### Device Discovery Diagnostic Script

For troubleshooting API discovery outside Home Assistant, this repository includes a helper script:

```bash
IQUA_USERNAME=user@example.com IQUA_PASSWORD=secret python3 scripts/query_devices.py --raw
```

Optional arguments:
- `--api-type iqua` or `--api-type iqua2`
- `--api-url https://example/v1` for testing a custom endpoint
- `--raw` to print the full `/devices` response after the summarized device list

The script prints the fields the config flow uses to build the device picker, including discovered device serial and product serial values.

## Troubleshooting

### Common Issues

**Integration not appearing in HACS:**
- Ensure you've added the custom repository URL correctly
- Check that the category is set to "Integration"
- Refresh HACS and try searching again

**Authentication errors:**
- Verify your iQua app credentials are correct
- Check that your iQua account has access to the water softener
- **Try switching API type** - if you're using iQua but your account is on iQua2 (or vice versa), authentication will fail

**No devices found during setup:**
- Confirm the water softener appears in the official iQua app for the same account
- Try the other API type (`iQua` vs `iQua2`)
- Run `scripts/query_devices.py --raw` to inspect what the API returns for your account

**No real-time updates:**
- Check if "Enable Real-time Updates" is enabled in integration options
- Verify your Home Assistant has internet connectivity
- Check the logs for WebSocket connection errors

**Sensors showing as unavailable:**
- Check Home Assistant logs for API errors
- Reconfigure the integration and confirm the correct discovered device is selected
- Ensure the water softener is online in the iQua app

### Enable Debug Logging

To help diagnose issues, add this to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.iqua_softener: debug
```

Then restart Home Assistant and check the logs under **Settings → System → Logs**.

## License
[MIT](https://choosealicense.com/licenses/mit/)
