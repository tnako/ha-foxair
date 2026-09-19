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
_ADDR_AC_CURRENT = 2057       # T35 AMP_X10 AC Input

# Compressor-draw threshold (kW): T54 above this means the compressor is
# really running. Pump/standby draw stays far below; compressor minimum
# duty is well above. 0.15 kW = 150 W.
_COMP_DRAW_MIN_KW = 0.15

_ADDR_RUN_STATUS = 2012       # Current run status: 0=Cooling 1=Heating
                              # 2=Defrost 3=Sterilization 4=DHW

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


def _cached(coord, key: str, fn):
    """Per-poll memo for computed values.

    All 8 computed entities + the energy accumulator re-derive the same
    values from the same coordinator data on every refresh; with the cache
    each heavy computation runs at most once per poll cycle. Keyed on the
    coordinator's data dict identity: a new poll replaces coord.data, so
    the cache invalidates itself (strong ref to the dict prevents id reuse
    collisions). One entry per coordinator — no growth.
    """
    cache = getattr(coord, "_computed_cache", None)
    if cache is None or cache[0] is not coord.data:
        cache = (coord.data, {})
        coord._computed_cache = cache
    results = cache[1]
    if key not in results:
        results[key] = fn()
    return results[key]


def _t59_matches_water_balance(coord) -> bool:
    """True when T59 agrees with the water-side balance flow*cp*dT.

    Used to un-suppress T59 when the compressor-frequency/bit evidence is
    absent but the unit really runs (v3.4 can report T31=0 and 2019 bit0=0
    for a whole poll while heating — real snapshot: T31=0, bit0=0, T54=600 W,
    T59=3.4 kW, water-side 3.3 kW -> match). In the pump-only phantom the
    T59 value wildly exceeds the water-side balance (dT is just the sensor
    offset), so no match. Requires dT > 0.8 K so sensor noise cannot fake
    a match, and T59 within 40..250% of the water-side power.
    """
    t59 = _cval(coord, _ADDR_HEATING_POWER)
    if t59 is None or t59 <= 0:
        return False
    flow = _cval(coord, _ADDR_FLOW)
    outlet = _cval(coord, 2046)
    inlet = _cval(coord, 2045)
    if flow is None or flow <= 0 or outlet is None or inlet is None:
        return False
    delta_t = outlet - inlet
    if delta_t <= 0.8:
        return False
    water_w = flow * 1000.0 * 4186.0 * delta_t / 3600.0
    t59_w = t59 * 1000.0  # T59 is kW (POWER_KW_X10 scaling), water side is W
    return 0.4 * water_w <= t59_w <= 2.5 * water_w


def _compressor_running(coord) -> Optional[bool]:
    """True when the compressor is actually running.

    Evidence, in order of reliability:
    1. T31 (2072) compressor frequency > 0.
    2. T54 (2054) electrical draw > 150 W AND T59 matches the water-side
       balance (see _t59_matches_water_balance): v3.4 firmware can report
       T31=0 and 2019 bit0=0 for a whole poll while the compressor runs.
       The balance check is what separates this from the pump-only
       phantom, where a nonzero T54 (300 W) coexisted with a T59 wildly
       above the water-side power.
    3. Bit 0 of the 2019 outputs bitfield ("Kompressor läuft").
    None = no evidence available (registers missing) — callers decide.
    """
    freq = _cval(coord, _COMPRESSOR_FREQ)
    if freq is not None and freq > 0:
        return True
    draw = _cval(coord, _ADDR_ELECTRICAL_POWER)
    if draw is not None and draw > _COMP_DRAW_MIN_KW and _t59_matches_water_balance(coord):
        return True
    if freq is not None:
        # T31 present and 0, and no corroborated draw -> compressor off
        # (the pump-only phantom case), unless bit0 disagrees.
        rec = coord.data.get(_OUTPUTS_WORD)
        if rec and rec.get("raw") is not None:
            return bool(int(rec["raw"]) & 0x1)
        return False
    rec = coord.data.get(_OUTPUTS_WORD)
    if rec and rec.get("raw") is not None:
        return bool(int(rec["raw"]) & 0x1)
    return None


def run_status_raw(coord) -> Optional[int]:
    """Raw 2012 run status (0=Cooling 1=Heating 2=Defrost 3=Steril 4=DHW)."""
    rec = coord.data.get(_ADDR_RUN_STATUS)
    if not rec:
        return None
    try:
        return int(rec.get("raw"))
    except (TypeError, ValueError):
        return None


def active_mode(coord) -> Optional[str]:
    """Classify what the unit is doing right now: heating/cooling/defrost/dhw.

    Mapping (register 2012):
      1 -> heating, 0 -> cooling, 2 -> defrost, 4 -> dhw.
      3 (sterilization) counts as dhw: it is an electric/DHW-side action.
      Defrost gets its own bucket: during a defrost cycle the energy
      flow reverses (heat leaves the house), so users want it visible
      separately from heating rather than folded into it. Power itself
      still comes from compute_thermal_power (same registers).
      2012 missing/unknown -> None (caller decides fallback).

    Memoized per poll cycle (see _cached): every computed entity reads it.
    """
    def _calc():
        rs = run_status_raw(coord)
        if rs == 1:
            return "heating"
        if rs == 0:
            return "cooling"
        if rs == 2:
            return "defrost"
        if rs == 3 or rs == 4:
            return "dhw"
        return None
    return _cached(coord, "active_mode", _calc)


def _heating_power(coord) -> Optional[float]:
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


def compute_heating_power(coord) -> Optional[float]:
    """Public heating-power entry point (memoized per poll cycle)."""
    def _calc():
        return _heating_power(coord)
    return _cached(coord, "heating_power", _calc)


def compute_thermal_power(coord, mode: str) -> Optional[float]:
    """Thermal power (W) for one active mode: heating | cooling | dhw | defrost.

    Same register sources as compute_heating_power (device T59 first, then
    flow/dT fallback), but gated on the unit's own run status (2012):
    the value only counts for the mode the unit reports it is in.
    Defrost is its own mode (2012=2, energy flow reverses); sterilization
    counts as DHW (see active_mode). A different active mode -> None so
    per-mode energy meters never cross-count. 2012 missing -> only
    "heating" falls back to the ungated value, keeping pre-v3.3 behaviour;
    cooling/dhw/defrost need 2012 evidence by design.
    """
    if mode not in ("heating", "cooling", "dhw", "defrost"):
        return None
    key = f"thermal_{mode}"

    def _calc():
        current = active_mode(coord)
        if current is None:
            if mode != "heating":
                return None
            return _heating_power(coord)
        if current != mode:
            return None
        return _heating_power(coord)
    return _cached(coord, key, _calc)


def compute_cooling_power(coord) -> Optional[float]:
    """Cooling power (W): flow x delta-T, only while run status = Cooling.

    The device has no cooling register; T59 is meaningless in cooling mode
    (heat extracted, not produced). Physical cooling power comes from the
    same water-side balance: P = flow * cp * |dT| where the outlet is
    COLDER than the inlet (delta_t < 0 while cooling). Gated on the
    compressor like the heating path: pump-only circulation in cooling
    mode shifts T01/T02 by sensor offset (~0.3 K) and would produce
    phantom cooling watts.
    """
    def _calc():
        if active_mode(coord) != "cooling":
            return None
        if _compressor_running(coord) is False:
            return None
        flow = _cval(coord, _ADDR_FLOW)
        if flow is None or flow <= 0:
            return None
        outlet = _cval(coord, 2046)
        inlet = _cval(coord, 2045)
        if outlet is None or inlet is None:
            return None
        delta_t = inlet - outlet  # positive while actually cooling
        if delta_t <= 0:
            return None
        return flow * 1000.0 * 4186.0 * delta_t / 3600.0
    return _cached(coord, "cooling_power", _calc)


def compute_electrical_power(coord, opts: dict) -> Optional[float]:
    """Compute electrical power from device register or external meter.

    Memoized per poll cycle keyed on elec_source (options rarely change;
    the external-meter state is re-read by the entity's own listener).
    """
    source = (opts or {}).get("elec_source", "foxair_register")
    return _cached(coord, f"elec_power_{source}", lambda: _electrical_power(coord, opts))


def _electrical_power(coord, opts: dict) -> Optional[float]:
    """Electrical power body (unmemoized; see compute_electrical_power)."""
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
    """Compute COP = heating_power / electrical_power (heating-mode COP).

    Gated on run status: when 2012 is present and reports cooling/DHW/
    sterilization, T59 does not reflect heating production and the COP
    must not count. Defrost (2012=2) still counts as heating COP: the
    compressor runs the same condenser circuit and the electrical draw
    is real heating-side consumption. 2012 missing -> old behaviour
    (pre-v3.3 units never expose 2012 reliably and their T54/T59 are 0
    whenever the compressor is off anyway).
    """
    current = active_mode(coord)
    if current is not None and current not in ("heating", "defrost"):
        return None
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


def compute_cop_mode(coord, opts: dict, mode: str) -> Optional[float]:
    """Per-mode COP: thermal power of that mode / total electrical power.

    mode: "heating" | "cooling" | "dhw". Only counts while the unit's run
    status (2012) reports that mode, so each COP reflects real operation.
    Electrical power is the total draw (T54 / external meter) — during DHW
    and cooling that is exactly the mode's consumption; during defrost it
    is charged to heating, matching the thermal side.
    """
    tp = compute_thermal_power(coord, mode)
    if mode == "cooling" and tp is None:
        tp = compute_cooling_power(coord)
    if tp is None:
        return None
    ep = compute_electrical_power(coord, opts)
    if ep is None or ep <= _ELEC_MIN_FOR_COP:
        return None
    cop = tp / ep
    if 0 < cop <= _COP_MAX:
        return round(cop, 2)
    return None
