from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Deque
from collections import deque

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, callback, State
from homeassistant.components.sensor import SensorEntity, PLATFORM_SCHEMA
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ATTR_SOURCE,
    ATTR_METHOD,
    ATTR_UPDATE_S,
    ATTR_WINDOW_S,
    ATTR_TAU_S,
    METHOD_TIME_SMA,
    METHOD_LOW_PASS,
    METHOD_INTEGRATOR,
    SUPPORTED_METHODS,
)

# ------------------------
# YAML schema
# ------------------------
CONF_NAME = "name"
CONF_UNIQUE_ID = "unique_id"
CONF_SOURCE = "source"
CONF_METHOD = "method"
CONF_UPDATE_S = "update_s"
CONF_WINDOW_S = "window_s"
CONF_TAU_S = "tau_s"
CONF_FORCE_UPDATE = "force_update"
CONF_ROUND = "round"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SOURCE): cv.entity_id,
        vol.Required(CONF_METHOD): vol.In(SUPPORTED_METHODS),
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_UPDATE_S, default=30): vol.All(vol.Coerce(float), vol.Range(min=1.0)),
        vol.Optional(CONF_WINDOW_S, default=60): vol.All(vol.Coerce(float), vol.Range(min=1.0)),
        vol.Optional(CONF_TAU_S, default=30): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        vol.Optional(CONF_FORCE_UPDATE, default=True): cv.boolean,
        vol.Optional(CONF_ROUND): vol.Coerce(int),
        vol.Optional(ATTR_UNIT_OF_MEASUREMENT): cv.string,
    }
)

# ------------------------
# Filter implementations
# ------------------------
class BaseFilter:
    def __init__(self):
        self.y = 0.0
        self.last_x: Optional[float] = None

    def tick(self, x: float, dt: float, now_s: float):
        raise NotImplementedError

class TimeSMA(BaseFilter):
    def __init__(self, window_s: float):
        super().__init__()
        self.window_s = window_s
        self.samples: Deque[tuple[float, float]] = deque()  # (timestamp_s, value)

    def tick(self, x: float, dt: float, now_s: float):
        # Drop samples outside window
        cutoff = now_s - self.window_s
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        # Add new sample
        self.samples.append((now_s, x))
        # Time-weighted average across the window by linear segments
        if len(self.samples) > 1:
            total_area = 0.0
            total_time = 0.0
            prev_t, prev_v = self.samples[0]
            for (t, v) in list(self.samples)[1:]:
                dt = t - prev_t
                area = 0.5 * (prev_v + v) * dt
                total_area += area
                total_time += dt
                prev_t, prev_v = t, v
            if total_time > 0:
                self.y = total_area / total_time
        else:
            self.y = x    # Only one sample

class LowPass(BaseFilter):
    def __init__(self, tau_s: float):
        super().__init__()
        self.tau = tau_s
        self.initialized = False

    def tick(self, x: float, dt: float, now_s: float):
        if not self.initialized:
            self.y = x
            self.initialized = True
            return
        # Discrete-time EMA with dt-adaptive alpha: alpha = 1 - exp(-dt/tau)
        alpha = 1.0 - pow(2.718281828, -dt / self.tau)
        self.y = (1 - alpha) * self.y + alpha * x

class Integrator(BaseFilter):
    def __init__(self):
        super().__init__()

    def tick(self, x: float, dt: float, now_s: float):
        # Trapezoidal rule when last_x available; otherwise rectangle
        if self.last_x is not None:
            self.y += 0.5 * (self.last_x + x) * dt
        else:
            self.y += x * dt

# ------------------------
# Sensor entity
# ------------------------
class TickFilterSensor(SensorEntity, RestoreEntity):
    def __init__(self, hass: HomeAssistant, name: str, source: str, method: str,
                 update_s: float, window_s: float, tau_s: float, unit: Optional[str],
                 unique_id: Optional[str], force_update: bool, rounding: Optional[int]):
        self.hass = hass
        self._attr_name = name
        self._attr_has_entity_name = True
        self._source = source
        self._method = method
        self._update_s = update_s
        self._window_s = window_s
        self._tau_s = tau_s
        self._round = rounding
        self._attr_native_value = None
        self._attr_force_update = force_update
        self._attr_native_unit_of_measurement = unit
        self._attr_extra_state_attributes = {
            ATTR_SOURCE: source,
            ATTR_METHOD: method,
            ATTR_UPDATE_S: update_s,
        }
        if unique_id:
            self._attr_unique_id = unique_id
        if method == METHOD_TIME_SMA:
            self.filter = TimeSMA(window_s)
            self._attr_extra_state_attributes[ATTR_WINDOW_S] = window_s
        elif method == METHOD_LOW_PASS:
            self.filter = LowPass(tau_s)
            self._attr_extra_state_attributes[ATTR_TAU_S] = tau_s
        elif method == METHOD_INTEGRATOR:
            self.filter = Integrator()
            self._attr_state_class = "total_increasing"
        else:
            raise ValueError(f"Unsupported method {method}")
        self._last_ts = datetime.now(timezone.utc).timestamp()
        self._last_src_ts: Optional[float] = None   # timestamp of last source state
        self._unsub = None
        self._unsub_state = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Restore previous state
        last_state = await self.async_get_last_state()
        if last_state:
            try:
                self.filter.y = float(last_state.state)
                self._attr_native_value = self.filter.y
            except ValueError:
                pass

        # Listen to source state changes for immediate updates
        self._unsub_state = async_track_state_change_event(self.hass, [self._source], self._state_listener)

        # Periodic ticker always runs; we decide inside whether to emit
        interval = timedelta(seconds = self._update_s / 4) # tick more often than update_s
        self._unsub = async_track_time_interval(self.hass, self._async_tick, interval)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    @callback
    async def _state_listener(self, event):
        new_state: State | None = event.data.get("new_state")
        if new_state is None or new_state.entity_id != self._source:
            return
        # Update last source event time
        now_s = datetime.now(timezone.utc).timestamp()
        self._last_src_ts = now_s
        # Set unit and scaling
        scale = 1.0
        dst_unit = self._attr_native_unit_of_measurement
        src_unit = new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if dst_unit is None:
            if self._method != METHOD_INTEGRATOR:
                dst_unit = src_unit
                self._attr_native_unit_of_measurement = dst_unit
        if src_unit is not None and dst_unit is not None:
            if src_unit == dst_unit:
                self._attr_state_class = new_state.attributes.get("state_class")
                self._attr_device_class = new_state.attributes.get("device_class")
            else:
                if self._method == METHOD_INTEGRATOR:
                    if src_unit in ("W", "kW"):
                        self._attr_device_class = "energy"
                if src_unit + 'h' == dst_unit:
                    scale = 3600.0
                elif 'k' + src_unit + 'h' == dst_unit:
                    scale = 3600000.0
        # Parse new input value
        try:
            x = float(new_state.state) / scale
        except (TypeError, ValueError):
            x = self.filter.last_x
        self._update_filter(now_s, x)

    @callback
    async def _async_tick(self, _now):
        now_s = datetime.now(timezone.utc).timestamp()
        # Only fallback-tick if we haven't seen a source event in update_s
        if self._last_src_ts is not None and (now_s - self._last_src_ts) < self._update_s:
            return
        self._update_filter(now_s, self.filter.last_x)

    def _update_filter(self, now_s: float, x: float):
        if x is None:
            return
        # Update filter state
        dt = max(0.0, now_s - self._last_ts)
        self._last_ts = now_s
        self.filter.tick(x, dt, now_s)
        self.filter.last_x = x
        if self._round is None:
            self._attr_native_value = self.filter.y
        else:
            self._attr_native_value = round(self.filter.y, self._round)
        self.async_write_ha_state()

# ------------------------
# Platform setup
# ------------------------
async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    source = config[CONF_SOURCE]
    method = config[CONF_METHOD]
    name = config.get(CONF_NAME) or f"{method} of {source}"
    update_s=float(config.get(CONF_UPDATE_S))
    window_s = float(config.get(CONF_WINDOW_S))
    tau_s = float(config.get(CONF_TAU_S))
    unit = config.get(ATTR_UNIT_OF_MEASUREMENT)
    unique_id = config.get(CONF_UNIQUE_ID)
    force_update = bool(config.get(CONF_FORCE_UPDATE))
    rounding = config.get(CONF_ROUND)

    ent = TickFilterSensor(
        hass,
        name=name,
        source=source,
        method=method,
        update_s=update_s,
        window_s=window_s,
        tau_s=tau_s,
        unit=unit,
        unique_id=unique_id,
        force_update=force_update,
        rounding=rounding,
    )
    async_add_entities([ent])

