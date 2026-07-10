import logging
import time
import json
import os
import threading
import asyncio
from enum import Enum, IntEnum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Callable

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None

import requests

try:
    import jwt  # optional (PyJWT)
except ImportError:
    jwt = None

try:
    import websockets
except ImportError:
    websockets = None

logger = logging.getLogger(__name__)


DEFAULT_API_BASE_URL = "https://api.myiquaapp.com/v1"


class IquaSoftenerState(str, Enum):
    ONLINE = "Online"
    OFFLINE = "Offline"


class IquaSoftenerVolumeUnit(IntEnum):
    GALLONS = 0
    LITERS = 1


class IquaSoftenerException(Exception):
    pass


@dataclass(frozen=True)
class IquaSoftenerData:
    timestamp: datetime
    model: str
    state: IquaSoftenerState
    device_date_time: datetime
    volume_unit: IquaSoftenerVolumeUnit
    current_water_flow: float
    today_use: int
    average_daily_use: int
    total_water_available: int
    days_since_last_regeneration: int
    salt_level: int
    salt_level_percent: int
    out_of_salt_estimated_days: int
    hardness_grains: int
    water_shutoff_valve_state: int
    enriched_data: Optional[Dict[str, Any]] = None  # Full enriched_data from API for additional sensors
    additional_properties: Optional[Dict[str, Any]] = None  # Full properties from debug API for detailed data


class IquaSoftener:
    def __init__(
        self,
        username: str,
        password: str,
        device_serial_number: Optional[str] = None,
        product_serial_number: Optional[str] = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
        enable_websocket: bool = True,
        external_realtime_data: Optional[Dict[str, Any]] = None,
    ):
        self._username: str = username
        self._password: str = password
        self._device_serial_number = device_serial_number
        self._product_serial_number = product_serial_number
        self._api_base_url: str = api_base_url
        
        self._session: Optional[requests.Session] = None
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._access_expires_at: Optional[int] = None
        self._device_id: Optional[str] = None  # Cache the device ID

        # WebSocket support
        self._enable_websocket = enable_websocket and websockets is not None
        self._websocket_uri: Optional[str] = None
        self._websocket_uri_cached_at: Optional[float] = None
        self._websocket_uri_cache_duration = 240  # Cache URI for 4 minutes (safely under 5-minute timeout)
        self._websocket_task: Optional[asyncio.Task] = None
        self._websocket_thread: Optional[threading.Thread] = None
        self._websocket_loop: Optional[asyncio.AbstractEventLoop] = None
        self._realtime_data: Dict[str, Any] = {}
        self._websocket_running = False
        self._websocket_lock = threading.Lock()
        self._websocket_lifecycle_lock = threading.Lock()
        self._websocket_connected_at: Optional[float] = None
        self._websocket_force_reconnect = False
        self._websocket_app_active_timeout = 300.0  # Default to 5 minutes (in seconds)
        self._websocket_last_message_at = 0.0
        # Reconnect to legacy API after 170 seconds to avoid the 3-minute timeout;
        # For the new API (iqua2), the socket can stay alive longer, so set a much larger duration (e.g., 60 minutes)
        if "iqua2.com" in self._api_base_url.lower():
            self._websocket_max_duration = 3600 # 60 minutes
        else:
            self._websocket_max_duration = 170  # Reconnect after 170 seconds (before 3 min timeout)
        self._websocket_backoff = 60  # Initial backoff time in seconds
        self._websocket_max_backoff = 1800  # Maximum backoff time (30 minutes)

        # Device detail caching to avoid 429 rate limit errors
        self._device_detail_cache: Optional[dict] = None
        self._device_detail_cached_at: Optional[float] = None
        self._device_detail_cache_duration = 120  # Cache device detail for 120 seconds
        self._device_detail_backoff = 60  # Initial backoff time in seconds
        self._device_detail_max_backoff = 1800  # Maximum backoff time (30 minutes)
        self._device_detail_next_retry_at: Optional[float] = None  # When to retry after rate limit

        # Rate-limit state parsed from API response headers.
        # Updated on every response so backoff adapts if the server policy changes.
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_limit: Optional[int] = None
        self._rate_limit_refill_interval: Optional[float] = None  # seconds per token

        # External real-time data (for Home Assistant integration)
        self._external_realtime_data = external_realtime_data
        
        # Callback for WebSocket data updates (for Home Assistant integration)
        self._on_websocket_data_update: Optional[Callable[[str], None]] = None
        
        # Callback for WebSocket connection state changes (for Home Assistant integration)
        self._on_websocket_state_change: Optional[Callable[[bool], None]] = None

    @property
    def device_serial_number(self) -> Optional[str]:
        return self._device_serial_number
    
    @property
    def product_serial_number(self) -> Optional[str]:
        return self._product_serial_number
    
    @property
    def websocket_connected(self) -> bool:
        """Return True if WebSocket is currently connected."""
        return self._websocket_connected_at is not None
    
    def set_websocket_data_update_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Register a callback function to be called when WebSocket data updates.
        
        Args:
            callback: Function that takes property_name (str) as parameter, or None to unregister
        """
        self._on_websocket_data_update = callback
    
    def set_websocket_state_change_callback(self, callback: Optional[Callable[[bool], None]]) -> None:
        """Register a callback function to be called when WebSocket connection state changes.
        
        Args:
            callback: Function that takes is_connected (bool) as parameter, or None to unregister
        """
        self._on_websocket_state_change = callback

    def get_data(self, use_cache_only: bool = False) -> IquaSoftenerData:
        device_id = self._get_device_id()
        device = self._get_device_detail(device_id, use_cache_only=use_cache_only)
        props = device.get("properties", {})
        enriched = device.get("enriched_data", {}).get("water_treatment", {})

        def val(name: str, default=None):
            return props.get(name, {}).get("value", default)

        def enriched_val(name: str, default=None):
            """Get value from enriched_data."""
            return enriched.get(name, default)

        def realtime_val(name: str, fallback_name: Optional[str] = None, default=None):
            """Get value from real-time data if available, otherwise fallback to API data."""
            realtime_value = self.get_realtime_property(name)
            if realtime_value is not None:
                return realtime_value
            logger.debug("Property %s not found", name)
            if fallback_name:
                return val(fallback_name, default)
            return val(name, default)

        model_desc = val("model_description", "Unknown Model")
        model_id = val("model_id", "N/A")

        # Get device date from properties or use current time
        device_date_str = val("device_date")
        if device_date_str:
            try:
                # Parse the device date, assuming it's in ISO format
                parsed_datetime = datetime.fromisoformat(device_date_str.rstrip("Z"))
                if ZoneInfo is not None:
                    device_date_time = parsed_datetime.replace(tzinfo=ZoneInfo("UTC"))
                else:
                    device_date_time = parsed_datetime.replace(tzinfo=None)
            except (ValueError, AttributeError):
                if ZoneInfo is not None:
                    device_date_time = datetime.now(tz=ZoneInfo("UTC"))
                else:
                    device_date_time = datetime.now()
        else:
            if ZoneInfo is not None:
                device_date_time = datetime.now(tz=ZoneInfo("UTC"))
            else:
                device_date_time = datetime.now()

        # Use real-time service_active if available
        if "iqua2.com" in self._api_base_url.lower():
            service_active = realtime_val("is_online", default=device.get("is_online", True))
        else:
            service_active = realtime_val("service_active", "service_active", True)

        if ZoneInfo is not None:
            timestamp = datetime.now(tz=ZoneInfo("UTC"))
        else:
            timestamp = datetime.now()

        return IquaSoftenerData(
            timestamp=timestamp,
            model=f"{model_desc} ({model_id})",
            state=(
                IquaSoftenerState.ONLINE
                if service_active
                else IquaSoftenerState.OFFLINE
            ),
            device_date_time=device_date_time,
            volume_unit=IquaSoftenerVolumeUnit(int(val("volume_unit_enum", 0))),
            # Use real-time current_water_flow if available
            current_water_flow=float(
                realtime_val("current_water_flow_gpm")
                or props.get("current_water_flow_gpm", {}).get("converted_value", 0.0)
            ),
            # Use enriched_data for today's usage if available
            today_use=int(
                enriched_val("gallons_used_today") or val("gallons_used_today", 0)
            ),
            average_daily_use=int(val("avg_daily_use_gals", 0)),
            # Use enriched_data for treated water available
            total_water_available=int(
                enriched_val("treated_water_available", {}).get("value")
                or val("treated_water_avail_gals", 0)
            ),
            # Use enriched_data for days since last regeneration
            days_since_last_regeneration=int(
                enriched_val("days_since_last_recharge")
                or val("days_since_last_regen", 0)
            ),
            salt_level=int(val("salt_level_tenths", 0) / 10),
            # Use enriched_data for salt level percent
            salt_level_percent=int(enriched_val("salt_level_percent") or 0),
            out_of_salt_estimated_days=int(val("out_of_salt_estimate_days", 0)),
            hardness_grains=int(val("hardness_grains", 0)),
            water_shutoff_valve_state=self._get_water_shutoff_valve_state(device),
            enriched_data=enriched,  # Include full enriched_data for additional sensors
            additional_properties=props,  # Include full properties from device detail API
        )

    def get_flow_and_salt(self) -> dict:
        """Return just flow (gpm) and salt level percent for quick dashboards."""
        # Try to get real-time flow first
        realtime_flow = self.get_realtime_property("current_water_flow_gpm")

        if realtime_flow is not None:
            flow = realtime_flow
        else:
            # Fallback to API data
            device_id = self._get_device_id()
            device = self._get_device_detail(device_id)
            props = device.get("properties", {})
            flow = props.get("current_water_flow_gpm", {}).get("converted_value", 0.0)

        # Salt level is typically not real-time, so get from API
        device_id = self._get_device_id()
        device = self._get_device_detail(device_id)
        salt = (
            device.get("enriched_data", {})
            .get("water_treatment", {})
            .get("salt_level_percent")
        )

        return {"flow_gpm": flow, "salt_percent": salt}

    def set_water_shutoff_valve(self, state: int):
        if state not in (0, 1):
            raise ValueError(
                "Invalid state for water shutoff valve (should be 0 or 1)."
            )

        device_id = self._get_device_id()
        url = f"/devices/{device_id}/command"

        # Convert state to action string: 1 = open, 0 = closed
        action = "open" if state == 1 else "close"
        payload = {"function": "water_shutoff_valve", "action": action}

        response = self._request("PUT", url, json=payload)
        if response.status_code != 200:
            raise IquaSoftenerException(
                f"Invalid status ({response.status_code}) for set water shutoff valve request"
            )
        response_data = response.json()
        return response_data

    def open_water_shutoff_valve(self):
        """Open the water shutoff valve (allow water flow) - state 1."""
        return self.set_water_shutoff_valve(1)

    def close_water_shutoff_valve(self):
        """Close the water shutoff valve (stop water flow) - state 0."""
        return self.set_water_shutoff_valve(0)

    def schedule_regeneration(self):
        """Schedule a regeneration cycle for the water softener."""
        device_id = self._get_device_id()
        url = f"/devices/{device_id}/command"
        payload = {"function": "regenerate", "action": "schedule"}

        response = self._request("PUT", url, json=payload)
        if response.status_code != 200:
            raise IquaSoftenerException(
                f"Invalid status ({response.status_code}) for schedule regeneration request"
            )
        response_data = response.json()
        return response_data

    def cancel_scheduled_regeneration(self):
        """Cancel a scheduled regeneration cycle."""
        device_id = self._get_device_id()
        url = f"/devices/{device_id}/command"
        payload = {"function": "regenerate", "action": "cancel"}

        response = self._request("PUT", url, json=payload)
        if response.status_code != 200:
            raise IquaSoftenerException(
                f"Invalid status ({response.status_code}) for cancel regeneration request"
            )
        response_data = response.json()
        return response_data

    def regenerate_now(self):
        """Start a regeneration cycle immediately."""
        device_id = self._get_device_id()
        url = f"/devices/{device_id}/command"
        payload = {"function": "regenerate", "action": "regenerate"}

        response = self._request("PUT", url, json=payload)
        if response.status_code != 200:
            raise IquaSoftenerException(
                f"Invalid status ({response.status_code}) for regenerate now request"
            )
        response_data = response.json()
        return response_data

    def get_devices(self) -> list:
        """Get list of all devices for the authenticated user."""
        return self._get_devices()

    def get_device_id(self) -> str:
        """Get the device ID for the configured serial number."""
        return self._get_device_id()

    def get_device_details(self) -> dict:
        """Get detailed device information for the configured device."""
        device_id = self._get_device_id()
        return self._get_device_detail(device_id)

    def get_device_settings(self) -> dict:
        """Get device settings and their current values.
        
        Returns:
            Dictionary with settings information including current values and options
        """
        device_id = self._get_device_id()
        url = f"/devices/{device_id}/settings"
        response = self._request("GET", url)
        if response.status_code != 200:
            raise IquaSoftenerException(
                f"Invalid status ({response.status_code}) for get device settings request"
            )
        return response.json()

    def set_device_setting(self, setting_name: str, setting_value: str) -> dict:
        """Set a device setting to a new value.
        
        Args:
            setting_name: The name of the setting (e.g., 'salt_type', 'regeneration_time')
            setting_value: The new value for the setting
            
        Returns:
            Response data from the API
        """
        import logging
        import requests
        logger = logging.getLogger(__name__)
        
        device_id = self._get_device_id()
        url = f"/devices/{device_id}/settings"
        
        # API expects: {"settings": {"setting_name": "value"}}
        payload = {"settings": {setting_name: setting_value}}
        
        try:
            logger.debug(f"Setting {setting_name} to {setting_value}")
            self._ensure_session()
            assert self._session is not None
            response = self._session.patch(
                f"{self._api_base_url}{url}",
                json=payload,
                timeout=30
            )
            
            if response.status_code not in [200, 201, 204]:
                try:
                    error_detail = response.json()
                    error_msg = f"Failed to set device setting. Status {response.status_code}: {error_detail}"
                except:
                    error_msg = f"Failed to set device setting. Status {response.status_code}: {response.text}"
                logger.error(error_msg)
                raise IquaSoftenerException(error_msg)
            
            # Handle cases where there's no response body (204 No Content)
            if response.status_code == 204:
                return {}
            try:
                return response.json()
            except:
                return {}
                    
        except requests.RequestException as e:
            error_msg = f"Failed to set device setting: {e}"
            logger.error(error_msg)
            raise IquaSoftenerException(error_msg)

    def has_water_shutoff_valve(self) -> bool:
        """Check if the device has a water shutoff valve installed."""
        try:
            device_id = self._get_device_id()
            device = self._get_device_detail(device_id)
            
            # Check for water_shutoff_valve in multiple locations
            valve_data = None
            
            # Check enriched_data first
            enriched = device.get("enriched_data", {}).get("water_treatment", {})
            valve_data = enriched.get("water_shutoff_valve", {})
            
            # If not in enriched_data, check properties
            if not valve_data:
                props = device.get("properties", {})
                valve_data = props.get("water_shutoff_valve", {})
            
            # If still not found, check device root level  
            if not valve_data:
                valve_data = device.get("water_shutoff_valve", {})
            
            # Check if valve is installed
            if isinstance(valve_data, dict):
                return valve_data.get("is_installed", False)
            
            return False
        except Exception as e:
            logger.error(f"Error checking water shutoff valve availability: {e}")
            return False

    def start_websocket(self):
        """Start WebSocket connection for real-time updates."""
        if not self._enable_websocket:
            logger.warning(
                "WebSocket support is disabled or websockets library not available"
            )
            return

        with self._websocket_lifecycle_lock:
            if self._websocket_running:
                logger.info("WebSocket already running")
                return

            self._websocket_running = True
            self._websocket_backoff = 60  # Reset backoff on start
            self._websocket_thread = threading.Thread(
                target=self._run_websocket_thread, daemon=True
            )
            self._websocket_thread.start()

    def stop_websocket(self):
        """Stop WebSocket connection."""
        with self._websocket_lifecycle_lock:
            if not self._websocket_running:
                return

            self._websocket_running = False
            
            # Clear WebSocket URI cache when stopping to get fresh URI on next start
            self._websocket_uri = None
            self._websocket_uri_cached_at = None
            
            # Clear device detail cache and reset backoff when stopping
            self._device_detail_cache = None
            self._device_detail_cached_at = None
            self._device_detail_backoff = 60
            self._device_detail_next_retry_at = None

            if self._websocket_loop and self._websocket_task:
                self._websocket_loop.call_soon_threadsafe(self._websocket_task.cancel)

            if self._websocket_thread:
                self._websocket_thread.join(timeout=5)

    def get_realtime_property(self, property_name: str) -> Optional[Any]:
        """Get a real-time property value from WebSocket data."""
        # Check external real-time data first (for Home Assistant integration)
        if self._external_realtime_data:
            prop_data = self._external_realtime_data.get(property_name)
            if prop_data:
                if prop_data.get("converted_property"):
                    return prop_data["converted_property"]["value"]
                return prop_data.get("value")

        # Fall back to internal WebSocket data
        with self._websocket_lock:
            prop_data = self._realtime_data.get(property_name)
            if prop_data:
                # Return converted_value if available, otherwise raw value
                if prop_data.get("converted_property"):
                    return prop_data["converted_property"]["value"]
                return prop_data.get("value")
            return None

    def update_external_realtime_data(self, realtime_data: Dict[str, Any]):
        """Update external real-time data (for Home Assistant integration)."""
        self._external_realtime_data = realtime_data

    def _update_cached_property_from_websocket(self, property_name: str, data: Dict[str, Any]) -> None:
        """Merge a WebSocket property update into the cached device detail."""
        if self._device_detail_cache is None:
            return

        properties = self._device_detail_cache.setdefault("properties", {})
        property_data = properties.setdefault(property_name, {})
        property_data["value"] = data.get("value")

        if "converted_value" in data:
            property_data["converted_value"] = data["converted_value"]
        elif data.get("converted_property"):
            converted_property = data["converted_property"]
            property_data["converted_value"] = converted_property.get("value")
            if converted_property.get("unit") is not None:
                property_data["converted_units"] = converted_property.get("unit")

        if "converted_units" in data:
            property_data["converted_units"] = data["converted_units"]

    def _build_websocket_url(self, ws_uri: str) -> str:
        """Resolve a WebSocket URI to a fully-qualified URL."""
        if ws_uri.startswith(("wss://", "ws://")):
            return ws_uri

        ws_base = self._api_base_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_host = ws_base.split("/")[0] + "//" + ws_base.split("//")[1].split("/")[0]
        if ws_uri.startswith("/"):
            return f"{ws_host}{ws_uri}"
        return f"{ws_host}/{ws_uri}"

    def get_websocket_uri(self) -> Optional[str]:
        """Get WebSocket URI for external use (like Home Assistant integration)."""
        try:
            device_id = self._get_device_id()
            response = self._request("GET", f"/devices/{device_id}/live")
            data = response.json()
            ws_uri = data.get("websocket_uri")
            if ws_uri:
                return self._build_websocket_url(ws_uri)
            return None
        except Exception as e:
            logger.error(f"Failed to get WebSocket URI: {e}")
            return None

    def _run_websocket_thread(self):
        """Run WebSocket client in a separate thread."""
        try:
            self._websocket_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._websocket_loop)
            self._websocket_loop.run_until_complete(self._websocket_client())
        except Exception as e:
            logger.error(f"WebSocket thread error: {e}")
        finally:
            if self._websocket_loop:
                self._websocket_loop.close()

    async def _websocket_client(self):
        """WebSocket client coroutine."""
        while self._websocket_running:
            try:
                # Get WebSocket URI
                ws_uri = await self._get_websocket_uri()
                if not ws_uri:
                    # Ensure we're marked as disconnected when we can't get the URI
                    self._websocket_connected_at = None

                    # _get_websocket_uri() already set _websocket_backoff from the
                    # rate-limit policy; use that value directly.
                    backoff_duration = self._websocket_backoff
                    logger.debug(f"Failed to get WebSocket URI (likely rate-limited), backing off for {backoff_duration:.1f} seconds")
                    await asyncio.sleep(backoff_duration)

                    # Exponential backoff for repeated failures
                    self._websocket_backoff = min(backoff_duration * 2, self._websocket_max_backoff)
                    continue

                # Reset backoff to one refill period on successful URI retrieval
                self._websocket_backoff = self._rate_limit_backoff()

                full_uri = self._build_websocket_url(ws_uri)
                logger.debug(f"Connecting to WebSocket: {full_uri}")

                if websockets is None:
                    # Ensure we're marked as disconnected when websockets library is unavailable
                    self._websocket_connected_at = None
                    logger.error("WebSocket library not available")
                    await asyncio.sleep(self._websocket_backoff)
                    self._websocket_backoff = min(self._websocket_backoff * 2, self._websocket_max_backoff)
                    continue

                async with websockets.connect(full_uri) as websocket:
                    logger.debug("WebSocket connected successfully")
                    self._websocket_task = asyncio.current_task()
                    self._websocket_connected_at = time.time()
                    self._websocket_last_message_at = time.time()
                    
                    # Notify connection state change callback
                    if self._on_websocket_state_change:
                        try:
                            self._on_websocket_state_change(True)
                        except Exception as e:
                            logger.error(f"Error calling WebSocket state change callback: {e}")

                    try:
                        while self._websocket_running:
                            # Check if we've been connected too long (proactive reconnect)
                            if self._websocket_connected_at:
                                connection_duration = time.time() - self._websocket_connected_at
                                if connection_duration >= self._websocket_max_duration:
                                    logger.debug(
                                        f"WebSocket connection duration ({connection_duration:.1f}s) "
                                        f"exceeded max ({self._websocket_max_duration}s), reconnecting..."
                                    )
                                    break
                            
                            # Check if reconnect was requested (e.g. app_active is False)
                            if getattr(self, "_websocket_force_reconnect", False):
                                logger.debug("WebSocket reconnect requested (app_active=False), reconnecting...")
                                self._websocket_force_reconnect = False
                                break
                            
                            # Check if we've been inactive too long (idle timeout)
                            if self._websocket_last_message_at:
                                inactivity_duration = time.time() - self._websocket_last_message_at
                                if inactivity_duration >= self._websocket_app_active_timeout:
                                    logger.debug(
                                        f"WebSocket quiet for {inactivity_duration:.1f}s "
                                        f"(exceeded timeout of {self._websocket_app_active_timeout}s), reconnecting..."
                                    )
                                    break
                            
                            try:
                                # Use asyncio.wait_for to timeout if no message arrives
                                # This ensures we check connection duration even without messages
                                message = await asyncio.wait_for(
                                    websocket.recv(),
                                    timeout=30.0  # Check connection status every 30 seconds
                                )
                                
                                try:
                                    data = json.loads(message)
                                    await self._handle_websocket_message(data)
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Failed to parse WebSocket message: {e}")
                                except Exception as e:
                                    logger.error(f"Error handling WebSocket message: {e}")
                                    
                            except asyncio.TimeoutError:
                                # No message received within timeout - this is normal
                                # Just loop back to check connection duration
                                continue
                            except websockets.exceptions.ConnectionClosed:
                                logger.debug("WebSocket connection closed by server")
                                break
                    except asyncio.CancelledError:
                        logger.debug("WebSocket connection cancelled - shutting down gracefully")
                        break
                    finally:
                        # Log when we exit the message receive loop
                        if self._websocket_running:
                            logger.debug("WebSocket message receive loop exited unexpectedly while running=True")
                        else:
                            logger.debug("WebSocket message receive loop exited normally (running=False)")
                
                # WebSocket connection has ended (either normally or via break)
                # Mark as disconnected before attempting to reconnect
                self._websocket_connected_at = None
                logger.debug("WebSocket disconnected, will attempt to reconnect")
                
                # Notify connection state change callback
                if self._on_websocket_state_change:
                    try:
                        self._on_websocket_state_change(False)
                    except Exception as e:
                        logger.error(f"Error calling WebSocket state change callback: {e}")
                
                # Small delay before reconnecting to avoid tight loops
                if self._websocket_running:
                    logger.debug("Waiting 1 second before reconnect attempt")
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                # Handle cancellation during sleep or other async operations
                logger.debug("WebSocket client cancelled - shutting down gracefully")
                break
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"WebSocket connection error: {e}")
                self._websocket_connected_at = None
                
                # If we get a 400 error, the cached URI is invalid - clear it
                if "400" in error_str or "bad request" in error_str:
                    logger.debug("WebSocket URI rejected with 400 - clearing cached URI")
                    self._websocket_uri = None
                    self._websocket_uri_cached_at = None
                    # Use at least one full refill period when URI is invalid
                    self._websocket_backoff = max(self._rate_limit_backoff(), self._websocket_backoff)
                
                # Notify connection state change callback on error
                if self._on_websocket_state_change:
                    try:
                        self._on_websocket_state_change(False)
                    except Exception as callback_err:
                        logger.error(f"Error calling WebSocket state change callback: {callback_err}")
                
                if self._websocket_running:
                    logger.debug(f"Backing off for {self._websocket_backoff} seconds due to connection error")
                    try:
                        await asyncio.sleep(self._websocket_backoff)
                    except asyncio.CancelledError:
                        logger.debug("WebSocket backoff sleep cancelled - shutting down gracefully")
                        break
                    self._websocket_backoff = min(self._websocket_backoff * 2, self._websocket_max_backoff)

    async def _get_websocket_uri(self) -> Optional[str]:
        """Get WebSocket URI from the API with caching to reduce rate limit issues.
        
        Caches the URI for 4 minutes (safely under the 5-minute timeout) to reduce
        API calls. With 170-second reconnect interval, this saves ~1 API call per cycle.
        """
        try:
            # Check if we have a cached URI that's still valid
            if self._websocket_uri and self._websocket_uri_cached_at:
                cache_age = time.time() - self._websocket_uri_cached_at
                # CRITICAL: URIs always expire after 300 seconds - never use older cache
                if cache_age < 300:
                    logger.debug(
                        f"Using cached WebSocket URI (age: {cache_age:.1f}s / 300s max)"
                    )
                    return self._websocket_uri
                else:
                    logger.debug(f"Cached WebSocket URI expired (age: {cache_age:.1f}s >= 300s), fetching new one")
                    # Clear expired cache
                    self._websocket_uri = None
                    self._websocket_uri_cached_at = None
            
            # Fetch new URI from API
            device_id = self._get_device_id()
            response = self._request("GET", f"/devices/{device_id}/live")
            data = response.json()
            ws_uri = data.get("websocket_uri")
            
            # Cache the URI and reset backoff on success
            if ws_uri:
                self._websocket_uri = ws_uri
                self._websocket_uri_cached_at = time.time()
                # Reset backoff to one refill period on successful URI fetch
                self._websocket_backoff = self._rate_limit_backoff()
                logger.debug(f"Cached new WebSocket URI (valid for 300s)")
            
            return ws_uri
        except requests.HTTPError as e:
            # Clear stale cache on any error
            self._websocket_uri = None
            self._websocket_uri_cached_at = None
            
            # Check if it's a rate limit error (429)
            if e.response is not None and e.response.status_code == 429:
                backoff = self._rate_limit_backoff()
                logger.debug("Rate limited when fetching WebSocket URI - backing off for %.1fs", backoff)
                self._websocket_backoff = backoff
                return None
            else:
                backoff = self._rate_limit_backoff()
                logger.error(f"Failed to get WebSocket URI: {e} - backing off for {backoff:.1f}s")
                self._websocket_backoff = backoff
                return None
        except Exception as e:
            backoff = self._rate_limit_backoff()
            logger.error(f"Failed to get WebSocket URI: {e} - backing off for {backoff:.1f}s")
            # Clear cache on any error
            self._websocket_uri = None
            self._websocket_uri_cached_at = None
            self._websocket_backoff = backoff
            return None

    async def _handle_websocket_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket message."""
        # Update last message timestamp
        self._websocket_last_message_at = time.time()

        if data.get("type") == "property" and "name" in data:
            property_name = data["name"]
            with self._websocket_lock:
                self._realtime_data[property_name] = data
                self._update_cached_property_from_websocket(property_name, data)
            logger.debug(
                f"Updated real-time property: {property_name} = {data.get('value')}"
            )
            
            # Dynamically update timeout if app_active_timeout is received (assumed in minutes)
            if property_name == "app_active_timeout":
                try:
                    val = float(data.get("value", 5))
                    # Clamp the parsed value between 1 and 60 minutes for safety
                    clamped_val = max(1.0, min(val, 60.0))
                    self._websocket_app_active_timeout = clamped_val * 60.0
                    logger.debug(f"Updated WebSocket app_active_timeout to {self._websocket_app_active_timeout}s ({clamped_val}m)")
                except (ValueError, TypeError):
                    pass

            # The iqua2 API lets us know when the socket needs to be refreshed by sending a message that app_active is False,
            # so request a reconnect to restart the data stream
            if property_name == "app_active" and data.get("value") in (False, 0, "false", "False"):
                logger.debug("Received app_active = False, forcing WebSocket reconnect to keep data stream active")
                self._websocket_force_reconnect = True

            # Notify callback if registered (for Home Assistant integration)
            if self._on_websocket_data_update:
                try:
                    self._on_websocket_data_update(property_name)
                except Exception as e:
                    logger.error(f"Error calling WebSocket data update callback: {e}")

    def save_tokens(self, path: str):
        """Save authentication tokens to a file."""
        with open(path, "w") as f:
            json.dump(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "user_id": self._user_id,
                    "_access_expires_at": self._access_expires_at,
                },
                f,
            )

    def load_tokens(self, path: str):
        """Load authentication tokens from a file."""
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            data = json.load(f)
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        self._user_id = data.get("user_id")
        self._access_expires_at = data.get("_access_expires_at")

    def _get_water_shutoff_valve_state(self, device: dict) -> int:
        """Parse water shutoff valve state from API device data."""
        # Check enriched_data first (this is where it should be)
        enriched = device.get("enriched_data", {}).get("water_treatment", {})
        valve_data = enriched.get("water_shutoff_valve", {})
        # If not in enriched_data, check properties as fallback
        if not valve_data:
            props = device.get("properties", {})
            valve_data = props.get("water_shutoff_valve", {})

        # If still not found, check device root level
        if not valve_data:
            valve_data = device.get("water_shutoff_valve", {})

        if isinstance(valve_data, dict):
            # Check if valve is installed first
            is_installed = valve_data.get("is_installed", False)
            if not is_installed:
                return 0  # Default to closed if not installed
                
            status = valve_data.get("status", "closed")
            # Convert status string to int: "open" = 1, "closed" = 0
            return 1 if status == "open" else 0
        # Fallback for legacy numeric format
        return int(valve_data) if valve_data is not None else 0

    def _get_device_id(self) -> str:
        """Get the device ID for the configured serial number."""
        if self._device_id is not None:
            return str(self._device_id)

        if not self._device_serial_number and not self._product_serial_number:
            raise IquaSoftenerException(
                "Either device_serial_number or product_serial_number must be provided"
            )

        # Get all devices and find the one with matching serial number
        devices = self._get_devices()
        for device in devices:
            props = device.get("properties", {})
            
            # Check device_serial_number field if provided
            if self._device_serial_number:
                device_serial = props.get("serial_number", {}).get("value")
                if device_serial == self._device_serial_number:
                    self._device_id = device["id"]
                    return str(self._device_id)
            
            # Check product_serial_number field if provided
            if self._product_serial_number:
                product_serial = props.get("product_serial_number", {}).get("value")
                if product_serial == self._product_serial_number:
                    self._device_id = device["id"]
                    return str(self._device_id)

        # Build error message based on what was provided
        if self._device_serial_number and self._product_serial_number:
            identifier = f"device serial number '{self._device_serial_number}' or product serial number '{self._product_serial_number}'"
        elif self._device_serial_number:
            identifier = f"device serial number '{self._device_serial_number}'"
        else:
            identifier = f"product serial number '{self._product_serial_number}'"
        
        raise IquaSoftenerException(
            f"Device with {identifier} not found"
        )

    def _get_devices(self) -> list:
        """Get list of all devices for the authenticated user."""
        r = self._request("GET", "/devices")
        data = r.json()
        return data.get("data", [])

    def _ensure_session(self):
        """Ensure we have a session object."""
        if self._session is None:
            self._session = requests.Session()

    def _set_tokens(self, access_token: str, refresh_token: Optional[str]):
        """Set authentication tokens and update session headers."""
        self._access_token = access_token
        self._refresh_token = refresh_token
        if jwt:
            try:
                decoded = jwt.decode(access_token, options={"verify_signature": False})
                exp = decoded.get("exp")
                if exp:
                    self._access_expires_at = int(exp) - 60
            except Exception:
                self._access_expires_at = None

        self._ensure_session()
        # After _ensure_session(), _session should not be None
        assert self._session is not None, "Session should be initialized"
        if self._access_token:
            self._session.headers.update(
                {"Authorization": f"Bearer {self._access_token}"}
            )

    def _is_token_expired(self) -> bool:
        """Check if the current access token is expired."""
        if not self._access_token:
            return True
        if self._access_expires_at is None:
            return False
        return time.time() >= self._access_expires_at

    def _login(self) -> Dict[str, Any]:
        """Authenticate with the API and get tokens."""
        self._ensure_session()
        # After _ensure_session(), _session should not be None
        assert self._session is not None, "Session should be initialized"
        url = f"{self._api_base_url}/auth/login"
        payload = {"email": self._username, "password": self._password}
        try:
            r = self._session.post(url, json=payload, timeout=15)
        except requests.exceptions.RequestException as ex:
            raise IquaSoftenerException(f"Exception on login request ({ex})")

        if r.status_code == 401:
            raise IquaSoftenerException(f"Authentication error ({r.text})")
        if r.status_code != 200:
            raise IquaSoftenerException(f"Login failed: {r.status_code} {r.text}")

        data = r.json()
        self._set_tokens(data.get("access_token"), data.get("refresh_token"))
        self._user_id = data.get("user_id")
        return data

    def _refresh_access_token(self) -> Dict[str, Any]:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            raise IquaSoftenerException("No refresh token available")

        self._ensure_session()
        # After _ensure_session(), _session should not be None
        assert self._session is not None, "Session should be initialized"
        url = f"{self._api_base_url}/auth/refresh"
        payload = {"refresh_token": self._refresh_token}
        try:
            r = self._session.post(url, json=payload, timeout=15)
        except requests.exceptions.RequestException as ex:
            raise IquaSoftenerException(f"Exception on token refresh ({ex})")

        if r.status_code != 200:
            raise IquaSoftenerException(f"Refresh failed: {r.status_code} {r.text}")

        data = r.json()
        self._set_tokens(data.get("access_token"), data.get("refresh_token"))
        return data

    def _ensure_authenticated(self):
        """Ensure we have a valid authentication token."""
        if self._is_token_expired():
            try:
                if self._refresh_token:
                    self._refresh_access_token()
                else:
                    self._login()
            except IquaSoftenerException:
                self._login()

    @staticmethod
    def _parse_policy_header(policy: str) -> dict:
        """Parse a ratelimit-policy header value into a dict.

        Format: "<limit>;w=<window>;burst=<burst>;policy=<name>"
        Example: "5;w=60;burst=50;policy=token_bucket"
        Returns: {'limit': 5, 'w': 60, 'burst': 50, 'policy': 'token_bucket'}
        """
        result: dict = {}
        parts = policy.split(";")
        try:
            result["limit"] = int(parts[0])
        except (ValueError, IndexError):
            pass
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    result[k] = int(v)
                except ValueError:
                    result[k] = v
        return result

    def _parse_rate_limit_headers(self, response: requests.Response) -> None:
        """Extract rate-limit headers from a response and update internal state.

        Called after every API response so the integration always uses the
        current server-side policy rather than hard-coded constants.
        """
        remaining = response.headers.get("ratelimit-remaining")
        limit = response.headers.get("ratelimit-limit")
        policy = response.headers.get("ratelimit-policy")

        if remaining is not None:
            try:
                self._rate_limit_remaining = int(remaining)
            except ValueError:
                pass

        if limit is not None:
            try:
                self._rate_limit_limit = int(limit)
            except ValueError:
                pass

        if policy is not None:
            parsed = self._parse_policy_header(policy)
            window = parsed.get("w")
            base_limit = parsed.get("limit")
            if window and base_limit:
                self._rate_limit_refill_interval = window / base_limit
                logger.debug(
                    "Rate-limit policy: %s req/%ss burst=%s → refill every %.1fs",
                    base_limit, window, parsed.get("burst", "?"),
                    self._rate_limit_refill_interval,
                )

    def _rate_limit_backoff(self) -> float:
        """Return the minimum safe wait before the next API request.

        Uses the token refill interval derived from the ratelimit-policy header
        so the backoff automatically adapts when the server changes its policy.
        Falls back to 60 s if no policy header has been seen yet.
        """
        if self._rate_limit_refill_interval is not None:
            return self._rate_limit_refill_interval
        return 60.0

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an authenticated request to the API."""
        self._ensure_authenticated()
        self._ensure_session()

        # After _ensure_session(), _session should not be None
        assert self._session is not None, "Session should be initialized"

        url = (
            path
            if path.startswith("http")
            else f"{self._api_base_url.rstrip('/')}/{path.lstrip('/')}"
        )

        r = self._session.request(method, url, timeout=20, **kwargs)
        if r.status_code == 401 and self._refresh_token:
            try:
                self._refresh_access_token()
                r = self._session.request(method, url, timeout=20, **kwargs)
            except IquaSoftenerException:
                self._login()
                r = self._session.request(method, url, timeout=20, **kwargs)

        # Always parse rate-limit headers so backoff stays in sync with server policy.
        self._parse_rate_limit_headers(r)

        if r.status_code != 200:
            r.raise_for_status()
        return r

    def _get_device_detail(self, device_id: str, use_cache_only: bool = False) -> dict:
        """Get detailed device information with caching and backoff to avoid rate limits.
        
        The /detail-or-summary endpoint is rate-limited by the API.
        This method:
        - Caches responses for 120 seconds to reduce API calls
        - Implements exponential backoff on 429 rate limit errors
        - Returns stale cache during backoff period
        """
        current_time = time.time()
        
        # Check if we're in backoff period (rate limited)
        if not use_cache_only and self._device_detail_next_retry_at and current_time < self._device_detail_next_retry_at:
            if self._device_detail_cache is not None:
                time_until_retry = self._device_detail_next_retry_at - current_time
                logger.debug(
                    "In backoff period, using cached device detail (retry in %.1f seconds)",
                    time_until_retry
                )
                return self._device_detail_cache
            else:
                # No cache available during backoff - wait is over, allow retry
                logger.debug("Backoff period active but no cache available, allowing retry")
                self._device_detail_next_retry_at = None
        
        # Return cached data if available and (still fresh or cache-only requested)
        if self._device_detail_cache is not None and (
            use_cache_only
            or (
                self._device_detail_cached_at is not None
                and (current_time - self._device_detail_cached_at) < self._device_detail_cache_duration
            )
        ):
            logger.debug(
                "Using cached device detail (age: %.1f seconds, cache_only: %s)",
                current_time - (self._device_detail_cached_at or 0),
                use_cache_only
            )
            return self._device_detail_cache
        
        # Attempt to fetch fresh data
        try:
            r = self._request("GET", f"/devices/{device_id}/detail-or-summary")
            data = r.json()
            device_data = data.get("device", {})
            
            # Success - cache the result and reset backoff
            self._device_detail_cache = device_data
            self._device_detail_cached_at = current_time
            self._device_detail_backoff = self._rate_limit_backoff()  # Reset to one refill period
            self._device_detail_next_retry_at = None
            logger.debug("Fetched and cached fresh device detail data")
            
            return device_data
            
        except requests.exceptions.HTTPError as e:
            # Check if it's a 429 rate limit error
            if e.response and e.response.status_code == 429:
                # Seed the backoff from the current rate-limit policy on first 429,
                # then double on each subsequent failure (exponential backoff).
                if self._device_detail_backoff == 60:
                    self._device_detail_backoff = self._rate_limit_backoff()
                # Calculate next retry time with exponential backoff
                self._device_detail_next_retry_at = current_time + self._device_detail_backoff
                logger.debug(
                    "Rate limited (429) on device detail endpoint, backing off for %d seconds",
                    self._device_detail_backoff
                )
                
                # Double the backoff for next time (exponential backoff)
                self._device_detail_backoff = min(
                    self._device_detail_backoff * 2,
                    self._device_detail_max_backoff
                )
                
                # Return stale cache if available
                if self._device_detail_cache is not None:
                    cache_age = current_time - self._device_detail_cached_at if self._device_detail_cached_at else 0
                    logger.info(
                        "Using stale cached device detail during backoff (age: %.1f seconds)",
                        cache_age
                    )
                    return self._device_detail_cache
                else:
                    logger.error("Rate limited with no cache available")
                    raise
            else:
                # Other HTTP errors - return stale cache if available
                if self._device_detail_cache is not None:
                    logger.warning(
                        "HTTP error fetching device detail (will use stale cache): %s",
                        e
                    )
                    return self._device_detail_cache
                raise
                
        except Exception as e:
            # Any other errors - return stale cache if available
            if self._device_detail_cache is not None:
                logger.warning(
                    "Error fetching device detail (will use stale cache): %s",
                    e
                )
                return self._device_detail_cache
            raise
