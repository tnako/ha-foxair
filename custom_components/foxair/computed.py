"""Computed (derived) sensors for FoxAir: heating power, electrical power, COP."""

from typing import Optional

from .const import get_slave_id

# Register addresses for computed sensors
_ADDR_FLOW = 2077        # T39 FLOW_M3H_X100 Wasserdurchflussrate
_ADDR_FREQ = 2072        # T31 DIGI1 Kompressor-Betriebsfrequenz
_ADDR_ELECTRICAL_POWER = 2054   # T54 POWER_KW_X10 Elektrische Leistung
_ADDR_HEATING_POWER = 2059      # T59 POWER_KW_X10 Wärmeleistung
_ADDR_COP = 2060              # T60 COP_X100 COP
_ADDR_AC_VOLT = 2062          # T34 VOLT AC-Eingangsspannung
_ADDR_AC_CURRENT = 2057       # T35 AMP_X10 AC Input Current

# Firmware that first computes T54/T59/T60 (v3.3). Pre-3.3 units report 0
# there; compute_electrical_power falls back to AC V x A for them.
_FW_AC_VA = 33

# Firmware quirk (confirmed on v3.3 and v3.4; old v1.3 verified unaffected
# via diagnostics): with only the water pump running (compressor off), T59
# (2059) keeps counting heat produced — phantom heating that wrecks COP.
# Register 2012 (run_status: 0=Cooling, 1=Heating, 2=Defrost, 3=
# Sterilization, 4=DHW) is the unit's own answer to "is it really heating",
# but it is not a code register and stayed off most installs; the
# compressor evidence is enough: T31 (2072) compressor frequency > 0, else
# bit 0 of the 2019 outputs word ("Kompressor läuft"). No compressor = no
# heating, regardless of T59/dT. Pre-v3.3 units report T54/T59/T60 = 0
# whenever the compressor is off anyway, so the gate cannot hide real heat
# there.
_COMPRESSOR_FREQ = 2072     # T31 DIGI1 Kompressor-Betriebsfrequenz
_OUTPUTS_WORD = 2019        # BITFIELD: bit 0 = compressor actually running

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


def _compressor_running(coord) -> Optional[bool]:
    """True when the compressor is actually running.

    Primary evidence: T31 (2072) compressor frequency > 0. Fallback: bit 0
    of the 2019 outputs bitfield ("Kompressor läuft"). None = no evidence
    available (registers missing) — callers decide how to treat that.
    """
    freq = _cval(coord, _COMPRESSOR_FREQ)
    if freq is not None:
        return freq > 0
    rec = coord.data.get(_OUTPUTS_WORD)
    if rec:
        raw = rec.get("raw")
        if raw is not None:
            return bool(int(raw) & 0x1)
    return None


def compute_heating_power(coord) -> Optional[float]:
    """Compute heating power from flow and delta T (or use device register).

    Formula: P_heat = flow * 4.186 * delta_T * 1000 (Watts)
    But the device provides it directly at 2059 (POWER_KW_X10).
    """
    # Pump-only quirk (v3.3+ confirmed): T59 keeps counting while only the
    # water pump runs. Without a running compressor there is no heat
    # production — neither trust T59 nor the flow/dT fallback (pump-only
    # circulation shifts temps too). Missing evidence (None) keeps the old
    # behaviour: pre-v3.3 firmware reports T54/T59/T60 = 0 whenever the
    # compressor is off, and the v1.3 COP fix relies on the fallback there.
    comp_on = _compressor_running(coord)
    if comp_on is False:
        return None

    # Try device-provided heating power first (0 = unit does not compute it).
    hp = _cval(coord, _ADDR_HEATING_POWER)
    if hp is not None and hp > 0:
        return hp * 1000.0  # kW to W

    # Fallback: calculate from flow and temperatures
    # Need: flow (2077), inlet/outlet temps
    flow = _cval(coord, _ADDR_FLOW)  # m³/h
    if flow is None or flow <= 0:
        return None

    # Try to get delta T from available sensors
    # Outlet: 2046 (T02 Auslasswasser), Inlet: 2045 (T01 Einlasswasser).
    # NOTE: 2047 is T08 WW-Tanktemperatur (DHW tank), NOT the inlet.
    outlet = _cval(coord, 2046)
    inlet = _cval(coord, 2045)
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
    """Compute electrical power from device register or external meter."""
    source = (opts or {}).get("elec_source", "foxair_register")

    if source == "external_meter":
        entity_id = (opts or {}).get("external_meter_entity") or ""
        entity_id = entity_id.strip()
        if not entity_id:
            return None
        hass = getattr(coord, "hass", None)
        if hass is None:
            return None
        st = hass.states.get(entity_id)
        if st is None or st.state in (None, "", "unknown", "unavailable"):
            return None
        try:
            val = float(st.state)
        except (TypeError, ValueError):
            return None
        unit = (st.attributes.get("unit_of_measurement") or "").strip().lower()
        if unit in ("kw", "kilowatt"):
            val *= 1000.0
        return val

    if source == "foxair_register":
        # Device-provided electrical power at 2054 (kW * 10);
        # 0 = unit does not compute it. Pre-v3.3 firmware never computes
        # T54/T59/T60, so fall back to apparent power = AC volts (2062) x
        # amps (2057, 0.1 A) to keep COP alive. v3.3+ keeps register-only
        # behaviour (no estimate).
        ep = _cval(coord, _ADDR_ELECTRICAL_POWER)
        if ep is not None and ep > 0:
            return ep * 1000.0  # kW to W
        fw = coord.fw_version() if hasattr(coord, "fw_version") else 0
        if 0 < fw < _FW_AC_VA:  # 33 = v3.3; 0 = unknown → no estimate
            v = _cval(coord, _ADDR_AC_VOLT)
            a = _cval(coord, _ADDR_AC_CURRENT)
            if v is not None and a is not None:
                return v * a

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