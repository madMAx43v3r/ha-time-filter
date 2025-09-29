# Basic tests proving: (1) event-driven updates, (2) fallback ticking, (3) integrator math, (4) unique_id wiring.

from datetime import timedelta
from pathlib import Path
import pytest

from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import utcnow
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.time_filter import DOMAIN

async def test_event_driven_update_and_unique_id(hass):
    # Seed a source sensor
    hass.states.async_set("sensor.src_power", 100, {"unit_of_measurement": "W"})
    await hass.async_block_till_done()

    # Configure one EMA filter sensor with unique_id
    config = {
        "sensor": [
            {
                "platform": "time_filter",
                "name": "Load Power (EMA 30s, hybrid)",
                "source": "sensor.src_power",
                "method": "lowpass",
                "tau_s": 30,
                "update_s": 30,
                "round": 1,
                "unique_id": "tickfilter_test_lowpass",
            }
        ]
    }

    assert await async_setup_component(hass, "sensor", config)
    await hass.async_block_till_done()

    # Advance time
    async_fire_time_changed(hass, utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()

    # Changing the source should immediately update the filter entity
    hass.states.async_set("sensor.src_power", 200, {"unit_of_measurement": "W"})
    await hass.async_block_till_done()

    # After platform load, entity should be registered with our unique_id
    registry = er.async_get(hass)
    ent_id = registry.async_get_entity_id("sensor", DOMAIN, "tickfilter_test_lowpass")
    assert ent_id is not None

    state = hass.states.get(ent_id)
    assert state is not None
    assert state.attributes.get("unit_of_measurement") == "W"
    assert float(state.state) > 100.0
    assert float(state.state) < 200.0


async def test_fallback_tick_after_quiet_period(hass):
    # Create constant source value
    hass.states.async_set("sensor.src_power", 100, {"unit_of_measurement": "W"})

    config = {
        "sensor": [
            {
                "platform": "time_filter",
                "name": "Time SMA fallback",
                "source": "sensor.src_power",
                "method": "time_sma",
                "window_s": 30,
                "update_s": 10,  # short timeout for test
                "unique_id": "tickfilter_test_fallback",
            }
        ]
    }

    assert await async_setup_component(hass, "sensor", config)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    ent_id = registry.async_get_entity_id("sensor", DOMAIN, "tickfilter_test_fallback")
    assert ent_id is not None

    # Initial event initialized EMA to 100
    state0 = hass.states.get(ent_id)
    assert float(state0.state) == pytest.approx(100.0)

    # Advance time by > timeout to trigger fallback tick
    async_fire_time_changed(hass, utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()

    # Value should still be ~100 but `last_updated` must move (tick happened)
    state1 = hass.states.get(ent_id)
    assert state1.last_updated > state0.last_updated
    assert float(state1.state) == pytest.approx(100.0)


async def test_integrator_accumulates_with_time(hass):
    # Constant 50 W source
    hass.states.async_set("sensor.src_power", 50, {"unit_of_measurement": "W"})

    config = {
        "sensor": [
            {
                "platform": "time_filter",
                "name": "Energy integ",
                "source": "sensor.src_power",
                "method": "integrator",
                "update_s": 5,
                "unit_of_measurement": "Wh",
                "unique_id": "tickfilter_test_integrator",
            }
        ]
    }

    assert await async_setup_component(hass, "sensor", config)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    ent_id = registry.async_get_entity_id("sensor", DOMAIN, "tickfilter_test_integrator")
    assert ent_id is not None

    # After first event (init), advance 10 seconds to let two 5s ticks occur
    t0 = utcnow()
    async_fire_time_changed(hass, t0 + timedelta(seconds=6))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, t0 + timedelta(seconds=12))
    await hass.async_block_till_done()

    # Expected: 50 W × ~10 s = 500 W·s (rectangle rule in our fallback path)
    state = hass.states.get(ent_id)
    assert float(state.state) == pytest.approx(50 * 10 / 3600.0, rel=0.01)

