# iQua Softener Integration Tests

This directory contains comprehensive tests for the Home Assistant iQua Softener integration.

## Test Structure

- `conftest.py` - Shared test fixtures and utilities
- `test_config_flow.py` - Tests for the configuration flow
- `test_sensor.py` - Tests for sensor entities and coordinator
- `test_init.py` - Tests for integration setup and teardown
- `test_switch.py` - Tests for switch entities
- `test_manifest.py` - Tests for manifest and constants validation

## Running Tests

### Prerequisites

1. Python 3.14.2+ installed (required by Home Assistant 2026.11)
2. Virtual environment activated:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the package in development mode:
   ```bash
   pip install -e .
   pip install -r test-requirements.txt
   ```

### Run All Tests

```bash
# Using venv Python directly
venv/bin/python -m pytest tests/

# Or with activated venv
pytest tests/
```

### Run Specific Test Files

```bash
venv/bin/python -m pytest tests/test_config_flow.py
venv/bin/python -m pytest tests/test_sensor.py
venv/bin/python -m pytest tests/test_init.py
venv/bin/python -m pytest tests/test_switch.py
```

### Run with Verbose Output

```bash
venv/bin/python -m pytest tests/ -v
```

### Run Quietly (Summary Only)

```bash
venv/bin/python -m pytest tests/ -q
```

### Run Tests with Coverage

```bash
pytest --cov=custom_components.iqua_softener --cov-report=html
```

Coverage report will be generated in `htmlcov/` directory.

## Test Coverage

The tests cover:

- **Configuration Flow**: User setup, validation, and reconfiguration
- **Sensor Entities**: All sensor types, data updates, error handling
- **Switch Entities**: Valve control, optimistic updates, error handling
- **Integration Setup**: Entry setup, options handling, WebSocket management
- **Coordinator**: Data fetching, WebSocket operations, error recovery
- **Constants & Manifest**: Validation of configuration and metadata

## Mocking Strategy

Tests use comprehensive mocking to avoid external dependencies:

- `IquaSoftener` client is mocked for API calls
- `IquaSoftenerData` is mocked with realistic test data
- Home Assistant components are mocked where appropriate
- WebSocket operations are mocked

## Test Fixtures

Key fixtures provided in `conftest.py`:

- `hass`: Home Assistant test instance
- `mock_iqua_softener`: Auto-use mocked IquaSoftener client (patches both import locations)
- `mock_iqua_data`: Mocked IquaSoftenerData with realistic test values
- `config_entry_data`: Sample configuration data dictionary
- `mock_config_entry`: MockConfigEntry instance
- `init_integration`: Complete integration setup with coordinator and platforms

## Writing New Tests

When adding new tests, follow these patterns from reference components (Shelly, MQTT, Enphase Envoy):

### 1. Use the Walrus Operator Pattern

```python
# ✅ Correct - combines state retrieval and assertion
async def test_sensor_state(self, hass, init_integration):
    """Test sensor state."""
    assert (state := hass.states.get("sensor.example"))
    assert state.state == "expected_value"

# ❌ Avoid - prone to timing issues
async def test_sensor_state(self, hass, init_integration):
    """Test sensor state."""
    await hass.async_block_till_done()  # init_integration already does this
    state = hass.states.get("sensor.example")
    assert state is not None
```

### 2. Entity ID Mapping

Home Assistant generates entity IDs from the `name` field in `SensorEntityDescription`:
- `name="Date/time"` → `sensor.date_time`
- `name="Today water usage"` → `sensor.today_water_usage`
- `name="Water Shutoff Valve"` → `switch.water_shutoff_valve`

**Always verify actual entity IDs in logs when writing tests!**

### 3. State Value Formatting

Match the actual state format returned by entities:
- Floats: `"50.0"` not `"50"`
- Capitalized: `"Online"` not `"online"`
- Check actual output in entity state

### 4. Test Organization

```python
class TestComponentName:
    """Test component functionality."""
    
    async def test_specific_feature(self, hass, init_integration):
        """Test description."""
        # Arrange (setup is in fixtures)
        
        # Act
        assert (state := hass.states.get("sensor.example"))
        
        # Assert
        assert state.state == "expected"
```

### 5. Avoiding Common Pitfalls

- ❌ Don't add extra `await hass.async_block_till_done()` after `init_integration`
- ❌ Don't assume entity ID format - check the actual registration
- ❌ Don't use device_class checks on entities that don't have them (e.g., switches)
- ✅ Use the exact fixture names from `conftest.py`
- ✅ Test both success and failure paths

## IDE Configuration

### VS Code / Pylance

The project includes configuration files for proper IDE support:

- **pyrightconfig.json**: Configures type checking and venv recognition
- **.vscode/settings.json**: VS Code-specific Python settings

If you see import errors for `pytest_homeassistant`:
1. Ensure your virtual environment is activated
2. Reload the VS Code window: `Ctrl+Shift+P` → "Reload Window"
3. Check that `python.defaultInterpreterPath` points to `venv/bin/python`

The `reportMissingImports` is set to `"none"` because `pytest-homeassistant` doesn't include a `py.typed` marker file.

## Test Results

Current test status: **30/30 passing** ✅

```
tests/test_sensor.py: 19 tests
tests/test_switch.py: 11 tests
```

## Continuous Integration

These tests are designed to run in CI environments and provide good coverage for ensuring code quality and preventing regressions.