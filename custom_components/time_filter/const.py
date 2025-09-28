from __future__ import annotations

ATTR_SOURCE = "source"
ATTR_METHOD = "method"
ATTR_UPDATE_S = "update_s"
ATTR_WINDOW_S = "window_s"
ATTR_TAU_S = "tau_s"

METHOD_TIME_SMA = "time_sma"
METHOD_LOW_PASS = "lowpass"
METHOD_INTEGRATOR = "integrator"
SUPPORTED_METHODS = {METHOD_TIME_SMA, METHOD_LOW_PASS, METHOD_INTEGRATOR}
