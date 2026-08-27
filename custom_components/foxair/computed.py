"""Computed (derived) sensors: heating power, electrical power, COP.

These are calculated from raw FoxAir register values rather than read directly.

Heating power uses the classic water-side formula
    P[W] = (flow_m3h / 3600) * rho * cp * dT
with a small EMA smoother + "hold-last-good" guard on the (notoriously flaky)
water-flow reading, and a hard zero when the compressor is off.

Electrical power used for COP has a configurable source:
  - "foxair_register" : the device's own Unit Power register 2054 (POWER_KW_X10,
                         /10 kW) — accurate, no calibration needed (default).
  - "foxair_v_a"      : V(2062) x I(2057) with user-tunable gain/offset so the
                         imprecise V/A sensors can be corrected against a real meter.
  - "external_meter"  : an external HA power-meter entity (e.g. a Shelly/meters
                         clamp) — most accurate if the user has one.

COP = heating_power / electrical_power, guarded against standby/garbage values.
"""
import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, main_device

_LOGGER = logging.getLogger(__name__)

# --- physical constants (water) ---
RHO = 1000.0     # kg/m^3
CP = 4186.0      # J/(kg*K)

# --- register addresses (values already pre-scaled by coordinator.scaled) ---
ADDR_FLOW = 2077    # FLOW_M3H_X100 -> m3/h
ADDR_T_IN = 2045    # Einlasswassertemperatur (inlet)  TEMP1 -> degC
ADDR_T_OUT = 2046   # outlet water temp               TEMP1 -> degC
ADDR_FREQ = 2072    # compressor operation frequency  HZ   -> Hz
ADDR_VOLT = 2062    # AC input voltage                VOLT -> V
ADDR_I = 2057       # AC input current (legacy)       RAW  -> raw counts (calibrate!)
ADDR_UNIT_POWER = 2054  # Unit Power                   POWER_KW_X10 -> /10 kW

# --- defaults for the V/A calibration option ---
DEFAULT_V_GAIN = 1.0
DEFAULT_V_OFFSET = 0.0
DEFAULT_I_GAIN = 0.1   # 2057 raw counts -> ~A (legacy modbus used scale 0.1)
DEFAULT_I_OFFSET = 0.0

EMA_ALPHA = 0.3       # flow smoother factor
FLOW_MIN = 0.3        # m3/h below this the flow signal is meaningless
FLOW_MAX = 10.0       # m3/h above this the flow signal is clearly bogus
P_MAX = 20000.0       # W, sanity clamp on heating power
COP_MAX = 8.0         # COP above this is physically implausible
ELEC_MIN_FOR_COP = 300.0  # W; ignore COP while essentially idle


def _val(coord, addr):
    rec = coord.data.get(addr)
    if not rec:
        return None
    v = rec.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_heating_power(coord):
    """Heating power in W from water flow x dT, or None.

    Uses an EMA smoother + "hold-last-good" guard on the (flaky) flow reading
    and forces zero when the compressor is off. The EMA state lives on the
    coordinator so it survives entity re-setup.
    """
    flow = _val(coord, ADDR_FLOW)
    t_in = _val(coord, ADDR_T_IN)
    t_out = _val(coord, ADDR_T_OUT)
    freq = _val(coord, ADDR_FREQ)
    if None in (flow, t_in, t_out, freq):
        return None
    ema = getattr(coord, "_flow_ema", 0.0)
    if freq <= 0:
        coord._flow_ema = 0.0
        return None
    if flow > 0:
        if ema <= 0:
            ema = flow
        else:
            ema = ema + EMA_ALPHA * (flow - ema)
    coord._flow_ema = ema
    if ema < FLOW_MIN or ema > FLOW_MAX:
        return None
    dT = t_out - t_in
    if dT <= 0:
        return None
    p = (ema / 3600.0) * RHO * CP * dT
    if not (0 < p < P_MAX):
        return None
    return p


def compute_electrical_power(coord, options):
    """Return electrical power in W from the configured source, or None."""
    source = (options or {}).get("elec_source", "foxair_register")
    if source == "external_meter":
        ent = (options or {}).get("external_meter_entity")
        if not ent:
            return None
        state = coord.hass.states.get(ent)
        if state is None:
            return None
        try:
            val = float(state.state)
        except (TypeError, ValueError):
            return None
        return val if val > 0 else None
    if source == "foxair_v_a":
        v_raw = _val(coord, ADDR_VOLT)
        i_raw = _val(coord, ADDR_I)
        if v_raw is None or i_raw is None:
            return None
        v_gain = float((options or {}).get("v_gain", DEFAULT_V_GAIN))
        v_off = float((options or {}).get("v_offset", DEFAULT_V_OFFSET))
        i_gain = float((options or {}).get("i_gain", DEFAULT_I_GAIN))
        i_off = float((options or {}).get("i_offset", DEFAULT_I_OFFSET))
        v = (v_raw + v_off) * v_gain
        i = (i_raw + i_off) * i_gain
        if v <= 0 or i <= 0:
            return None
        return v * i
    # default: device Unit Power register (/10 kW -> W)
    p = _val(coord, ADDR_UNIT_POWER)
    if p is None:
        return None
    w = p * 1000.0
    return w if w >= 0 else None


class FoxComputedSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord):
        super().__init__(coord)
        entry_id = getattr(coord, "_entry_id", None) or (
            getattr(coord, "config_entry", None)
            and coord.config_entry.entry_id
        )
        self._attr_device_info = main_device(entry_id)

    @property
    def _opts(self):
        return self.coordinator.entry.options


class FoxHeatingPowerSensor(FoxComputedSensor):
    _attr_unique_id = "foxair_heating_power"
    _attr_translation_key = "foxair_heating_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:radiator"

    @property
    def native_value(self):
        p = compute_heating_power(self.coordinator)
        return None if p is None else round(p, 1)

    @property
    def extra_state_attributes(self):
        try:
            flow = _val(self.coordinator, ADDR_FLOW)
            freq = _val(self.coordinator, ADDR_FREQ)
            ema = getattr(self.coordinator, "_flow_ema", 0.0)
            return {
                "flow_raw_m3h": flow,
                "flow_smoothed_m3h": round(ema, 3),
                "compressor_freq_hz": freq,
            }
        except Exception:
            return {}


class FoxElectricalPowerSensor(FoxComputedSensor):
    _attr_unique_id = "foxair_electrical_power"
    _attr_translation_key = "foxair_electrical_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    @property
    def native_value(self):
        p = compute_electrical_power(self.coordinator, self._opts)
        if p is None:
            return None
        return round(p, 1)

    @property
    def extra_state_attributes(self):
        source = (self._opts or {}).get("elec_source", "foxair_register")
        return {"source": source}


class FoxCopSensor(FoxComputedSensor):
    _attr_unique_id = "foxair_cop"
    _attr_translation_key = "foxair_cop"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sigma"

    @property
    def native_value(self):
        hp = compute_heating_power(self.coordinator)
        if hp is None:
            return None
        ep = compute_electrical_power(self.coordinator, self._opts)
        if ep is None or ep <= ELEC_MIN_FOR_COP:
            return None
        cop = hp / ep
        if 0 < cop <= COP_MAX:
            return round(cop, 2)
        return None


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    add_entities(
        [
            FoxHeatingPowerSensor(coord),
            FoxElectricalPowerSensor(coord),
            FoxCopSensor(coord),
        ]
    )
