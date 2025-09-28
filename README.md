# ha-time-filter
Time based filters for HA that work correctly

## configuration.yaml — examples
```
sensor:
  - platform: time_filter
    name: "Load Power (EMA 30s, hybrid)"
    source: sensor.victora_load_power
    method: ema
    tau_seconds: 30
    dt_seconds: 5
    fallback_timeout_seconds: 30   # update on change; else tick after 30s
    unit_of_measurement: W
    round: 1
    emit_every_tick: true

  - platform: time_filter
    name: "Grid Import Energy (Integrator)"
    source: sensor.victorb_grid_power
    method: integrator
    dt_seconds: 10
    unit_of_measurement: "W·s"  # or convert downstream to Wh/kWh
    round: 2
    emit_every_tick: true

  - platform: time_filter
    name: "PV Power (Time SMA 60s)"
    source: sensor.victora_pv_power
    method: time_sma
    window_seconds: 60
    dt_seconds: 5
    unit_of_measurement: W
    round: 1
    emit_every_tick: true
```
