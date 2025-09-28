# ha-time-filter
Time based filters for HA that work correctly

## configuration.yaml — examples
```
sensor:
  - platform: time_filter
    name: "Load Power (Lowpass 30s)"
    source: sensor.victor_load_power
    method: lowpass
    tau_s: 30       # filter parameter (sec)
    update_s: 30    # update on change; else tick after ~30s

  - platform: time_filter
    name: "Grid Import Energy (Integrator)"
    source: sensor.victor_grid_power   # unit W or kW
    method: integrator
    update_s: 60    # update on change; else tick after ~60s
    unit_of_measurement: "kWh"

  - platform: time_filter
    name: "PV Power (Time SMA 60s)"
    source: sensor.victor_pv_power
    method: time_sma
    window_s: 60    # window size (sec)
    update_s: 10    # update on change; else tick after ~10s
```
