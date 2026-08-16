"""Test water shutoff valve status parsing in the vendored library.

The status enum comes from WaterShutoffValveStatus in
https://api.myiquaapp.com/v1/openapi.json
"""
import threading

import pytest

from custom_components.iqua_softener.vendor.iqua_softener.iqua import IquaSoftener


def _device(valve_data=None, properties=None):
    """Build a minimal device detail payload."""
    device = {"properties": properties or {}}
    if valve_data is not None:
        device["enriched_data"] = {"water_treatment": {"water_shutoff_valve": valve_data}}
    return device


class TestParseStatus:
    """Test _parse_water_shutoff_valve_status."""

    @pytest.mark.parametrize(
        "status", ["open", "close", "manual", "not_installed", "unknown", "error"]
    )
    def test_documented_statuses_pass_through(self, status):
        valve_data = {"status": status, "is_installed": True}

        assert IquaSoftener._parse_water_shutoff_valve_status(valve_data) == status

    def test_closed_is_not_a_valid_status(self):
        """The API says "close", not "closed" - anything else is unknown."""
        valve_data = {"status": "closed", "is_installed": True}

        assert IquaSoftener._parse_water_shutoff_valve_status(valve_data) == "unknown"

    def test_missing_status_on_uninstalled_valve(self):
        valve_data = {"is_installed": False}

        assert (
            IquaSoftener._parse_water_shutoff_valve_status(valve_data) == "not_installed"
        )

    def test_raw_property_shape_is_not_guessed(self):
        """The raw property's integer enum is undocumented - don't decode it."""
        valve_data = {"name": "water_shutoff_valve", "value": 2}

        assert IquaSoftener._parse_water_shutoff_valve_status(valve_data) is None

    def test_no_valve_data(self):
        assert IquaSoftener._parse_water_shutoff_valve_status({}) is None


class TestValveState:
    """Test _water_shutoff_valve_state, the on/off integer used by the switch."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("open", 1),
            ("close", 0),
            # Not on/off states - reporting these as closed would claim the
            # water is shut off when it may not be
            ("manual", None),
            ("error", None),
            ("unknown", None),
            ("not_installed", None),
            (None, None),
        ],
    )
    def test_only_open_and_close_are_boolean(self, status, expected):
        assert IquaSoftener._water_shutoff_valve_state(status) is expected


class TestLocateValveData:
    """Test _get_water_shutoff_valve_data's lookup order."""

    def test_prefers_enriched_data(self):
        device = _device(
            valve_data={"status": "open", "is_installed": True},
            properties={"water_shutoff_valve": {"value": 2}},
        )

        assert IquaSoftener._get_water_shutoff_valve_data(
            IquaSoftener.__new__(IquaSoftener), device
        ) == {"status": "open", "is_installed": True}

    def test_falls_back_to_properties(self):
        device = _device(properties={"water_shutoff_valve": {"value": 2}})

        assert IquaSoftener._get_water_shutoff_valve_data(
            IquaSoftener.__new__(IquaSoftener), device
        ) == {"value": 2}

    def test_non_dict_valve_data(self):
        device = {"water_shutoff_valve": 1}

        assert (
            IquaSoftener._get_water_shutoff_valve_data(
                IquaSoftener.__new__(IquaSoftener), device
            )
            == {}
        )


class TestDecodeRealtimeProperty:
    """Test decoding of the real-time `water_shutoff_valve` property.

    The property reads as "is the water shut off", so 1 is a closed valve and 0
    is an open one - the inverse of the status strings. Confirmed from a
    WebSocket capture of a close/re-open cycle (issue #11).
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1, "close"),
            (0, "open"),
            ("1", "close"),
            (1.0, "close"),
        ],
    )
    def test_known_values(self, value, expected):
        assert IquaSoftener._decode_water_shutoff_valve_property(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            # The WebSocket publishes a counter-like value under this property
            # name before immediately re-publishing the real one. Taken at face
            # value it is truthy, so the valve would read "open" every time it
            # was closed.
            704847373,
            704848105,
            2,  # seen on a device with no valve installed - meaning unknown
            -1,
            None,
            True,
            False,
            "manual",
            {},
        ],
    )
    def test_rejects_undecodable_values(self, value):
        assert IquaSoftener._decode_water_shutoff_valve_property(value) is None


class TestManualOverrideIgnoresRealtime:
    """`wsov_manual_override` carries no usable state and must not be read.

    In the issue #11 capture it pulses 1 -> junk -> 0 around every operation and
    settles at 0 regardless of valve position.
    """

    @pytest.mark.parametrize("value", [1, 0, 704847857])
    def test_realtime_value_never_reaches_the_flag(self, value):
        softener = _softener(
            _device({"status": "open", "is_installed": True, "manual_override": False}),
            realtime={"wsov_manual_override": value},
        )

        assert softener.get_data().water_shutoff_valve_manual_override is False

    def test_flag_comes_from_enriched_data(self):
        softener = _softener(
            _device({"status": "open", "is_installed": True, "manual_override": True}),
            realtime={"wsov_manual_override": 0},
        )

        assert softener.get_data().water_shutoff_valve_manual_override is True


def _softener(device, realtime=None):
    """Build an IquaSoftener with its network access stubbed out."""
    inst = IquaSoftener.__new__(IquaSoftener)
    inst._api_base_url = "https://api.myiquaapp.com/v1"
    inst._get_device_id = lambda: "device-1"
    inst._get_device_detail = lambda device_id, use_cache_only=False: device
    # Keep the caller's dict so a test can mutate it between get_data() calls
    values = {} if realtime is None else realtime
    inst.get_realtime_property = lambda name: values.get(name)
    return inst


def _websocket_softener(device):
    """Build a softener that ingests real WebSocket messages.

    Unlike `_softener`, `get_realtime_property` is left intact so messages have
    to travel the real store to be visible to `get_data`.
    """
    inst = _softener(device)
    del inst.get_realtime_property  # restore the class implementation
    inst._realtime_data = {}
    inst._external_realtime_data = None
    inst._websocket_lock = threading.Lock()
    inst._websocket_last_message_at = 0.0
    inst._device_detail_cache = None
    inst._on_websocket_data_update = None
    return inst


class TestRealtimePreference:
    """Test that live WebSocket values beat the poll-only enriched_data block."""

    def test_realtime_value_wins_over_stale_enriched_data(self):
        """A valve closed from the app shows up without waiting for a poll."""
        softener = _softener(
            _device({"status": "open", "is_installed": True}),
            realtime={"water_shutoff_valve": 1},
        )

        data = softener.get_data()

        assert data.water_shutoff_valve_status == "close"
        assert data.water_shutoff_valve_state == 0

    def test_spurious_value_leaves_state_alone(self):
        """The counter-like WebSocket value must not move the valve."""
        softener = _softener(
            _device({"status": "close", "is_installed": True}),
            realtime={"water_shutoff_valve": 704847373},
        )

        data = softener.get_data()

        assert data.water_shutoff_valve_status == "close"
        assert data.water_shutoff_valve_state == 0

    def test_error_status_is_not_overridden(self):
        """A valve fault stays visible; the raw property can't express it."""
        softener = _softener(
            _device(
                {
                    "status": "error",
                    "is_installed": True,
                    "error_code": "both_switch_error",
                }
            ),
            realtime={"water_shutoff_valve": 1},
        )

        data = softener.get_data()

        assert data.water_shutoff_valve_status == "error"
        assert data.water_shutoff_valve_state is None
        assert data.water_shutoff_valve_error_code == "both_switch_error"

    def test_no_realtime_data_uses_enriched(self):
        softener = _softener(_device({"status": "open", "is_installed": True}))

        data = softener.get_data()

        assert data.water_shutoff_valve_status == "open"
        assert data.water_shutoff_valve_state == 1


class TestCaptureReplay:
    """Replay the WebSocket capture from issue #11.

    The valve started open in normal operation. The user closed it from the
    iQua app - which is what first pushes the property onto the socket - and
    later re-opened it. Includes the spurious counter value the socket emits
    alongside the real ones.
    """

    CAPTURE = [
        # (elapsed seconds, value, expected status after this message)
        (12.2, 1, "close"),  # closed from the app
        (17.4, 704847373, "close"),  # spurious - must not disturb the state
        (17.4, 1, "close"),
        (18.3, 1, "close"),
        (71.3, 1, "close"),
        (92.0, 1, "close"),
        (101.8, 1, "close"),
        (133.5, 0, "open"),  # re-opened from the app
        (138.0, 0, "open"),
        (138.5, 0, "open"),
        (194.9, 0, "open"),
    ]

    async def test_replay_tracks_the_valve(self):
        """Status follows the valve and never flips on the spurious value.

        Drives the real WebSocket ingest path so the spurious message is
        rejected before it can displace the last good value.
        """
        # enriched_data is deliberately stale and wrong, as it would be between
        # polls - every correct answer here has to come from the live property
        softener = _websocket_softener(_device({"status": "manual", "is_installed": True}))

        for elapsed, value, expected in self.CAPTURE:
            await softener._handle_websocket_message(
                {"type": "property", "name": "water_shutoff_valve", "value": value}
            )
            status = softener.get_data().water_shutoff_valve_status

            assert status == expected, f"at t={elapsed}s, value={value}"

    async def test_spurious_message_is_not_stored(self):
        """The bad value never reaches the real-time store at all."""
        softener = _websocket_softener(_device({"status": "open", "is_installed": True}))

        await softener._handle_websocket_message(
            {"type": "property", "name": "water_shutoff_valve", "value": 0}
        )
        await softener._handle_websocket_message(
            {"type": "property", "name": "water_shutoff_valve", "value": 704847373}
        )

        assert softener.get_realtime_property("water_shutoff_valve") == 0

    async def test_valid_updates_still_notify_listeners(self):
        """Dropping bad messages must not stop good ones waking the coordinator."""
        softener = _websocket_softener(_device({"status": "open", "is_installed": True}))
        notified = []
        softener._on_websocket_data_update = notified.append

        for value in (1, 704847373, 0):
            await softener._handle_websocket_message(
                {"type": "property", "name": "water_shutoff_valve", "value": value}
            )

        assert notified == ["water_shutoff_valve", "water_shutoff_valve"]

    def test_naive_decoding_would_have_failed(self):
        """Guard the guard: bool() reads the capture's junk as a real position."""
        spurious = [v for _, v, _ in self.CAPTURE if v not in (0, 1)]

        assert spurious, "capture should contain the spurious value"
        assert all(bool(v) for v in spurious)
