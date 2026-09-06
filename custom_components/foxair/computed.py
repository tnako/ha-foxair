"""Computed (derived) sensors for FoxAir: heating power, electrical power, COP."""

from typing import Optional

from .const import get_slave_id

# Register addresses for computed sensors
_ADDR_FLOW = 2077        # T39 FLOW_M3H_X100 Wasserdurchflussrate
_ADDR_FREQ = 2072        # T31 DIGI1 Kompressor-Betriebsfrequenz
_ADDR_ELECTRICAL_POWER = 2054   # T54 POWER_KW_X10 Elektrische Leistung
_ADDR_HEATING_POWER = 2059      # T59 POWER_KW_X10 Wärmeleistung
_ADDR_COP = 2060              # T60 COP_X100 COP

# COP calculation constants
_ELEC_MIN_FOR_COP = 100     # Minimum electrical power (W) for valid COP
_COP_MAX = 15.0             # Maximum plausible COP


def _cval(coord, addr: int) -> Optional[float]:
    """Get scaled value from coordinator data."""
    rec = coord.data.get(addr)
    if not rec:
        return None
    v = rec.get("value")
    return float(v) if v is not None else None


def compute_heating_power(coord) -> Optional[float]:
    """Compute heating power from flow and delta T (or use device register).

    Formula: P_heat = flow * 4.186 * delta_T * 1000 (Watts)
    But the device provides it directly at 2059 (POWER_KW_X10).
    """
    # Try device-provided heating power first
    hp = _cval(coord, _ADDR_HEATING_POWER)
    if hp is not None:
        return hp * 1000.0  # kW to W

    # Fallback: calculate from flow and temperatures
    # Need: flow (2077), inlet/outlet temps
    flow = _cval(coord, _ADDR_FLOW)  # m³/h
    if flow is None or flow <= 0:
        return None

    # Try to get delta T from available sensors
    # Outlet: 2046, Inlet: 2047 (or similar)
    outlet = _cval(coord, 2046)
    inlet = _cval(coord, 2047)
    if outlet is None or inlet is None:
        return None

    delta_t = outlet - inlet
    if delta_t <= 0:
        return None

    # P = flow * density * cp * delta_T
    # flow in m³/h, density ~1000 kg/m³, cp ~4186 J/(kg·K)
    # P(W) = flow(m³/h) * 1000 * 4186 * delta_T / 3600
    return flow * 1000.0 * 4186.0 * delta_t / 3600.0


def compute_electrical_power(coord, opts: dict) -> Optional[float]:
    """Compute electrical power from device register or estimation."""
    source = (opts or {}).get("elec_source", "foxair_register")

    if source == "foxair_register":
        # Device-provided electrical power at 2054 (kW * 10)
        ep = _cval(coord, _ADDR_ELECTRICAL_POWER)
        if ep is not None:
            return ep * 1000.0  # kW to W

    # Could add other sources here (external meter, etc.)
    return None


def compute_cop(coord, opts: dict) -> Optional[float]:
    """Compute COP = heating_power / electrical_power."""
    hp = compute_heating_power(coord)
    if hp is None:
        return None
    ep = compute_electrical_power(coord, opts)
    if ep is None or ep <= _ELEC_MIN_FOR_COP:
        return None
    cop = hp / ep
    if 0 < cop <= _COP_MAX:
        return round(cop, 2)
    return None