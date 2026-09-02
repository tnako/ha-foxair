from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, EXPERT_BLOCKS, DEVICE, POPULAR_ADDRS, device_for_addr, main_device, entity_sort_key, DTYPE_SPEC, get_device_prefix

# Build DTYPE_MAP from DTYPE_SPEC for backwards compatibility
DTYPE_MAP = {}
for dtype, spec in DTYPE_SPEC.items():
    device_class = getattr(SensorDeviceClass, spec["device_class"].upper()) if spec["device_class"] else None
    state_class = getattr(SensorStateClass, spec["state_class"].upper()) if spec["state_class"] else None
    DTYPE_MAP[dtype] = (device_class, spec["unit"], state_class)

HIDDEN = {2057}

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    # ensure metadata ready for category logic
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    # sort by tabs.txt order: each menu and each entity in required order
    def _sensor_key(item):
        addr, rec = item
        info = rec.get("info", {}) if isinstance(rec, dict) else {}
        meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        block = (meta.get("block") or info.get("block") or "")
        code = (meta.get("code") or info.get("code") or "")
        return entity_sort_key(addr, code, block)
    for addr, rec in sorted(coord.data.items(), key=_sensor_key):
        if rec.get("info", {}).get("type") == "BLOCK":
            continue
        # honor metadata blocked
        meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        if meta.get("risk") == "blocked" or meta.get("hidden"):
            continue
        # expert-gated (whole expert blocks + dangerous) sensors: skip unless expert on
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        if meta.get("editable") and meta.get("platform") in ("number", "select", "time"):
            continue
        ents.append(FoxSensor(coord, addr))
    ents.append(FoxHeatingCurveTargetSensor(coord))
    # computed (derived) sensors: heating power, electrical power, COP
    ents.append(FoxHeatingPowerSensor(coord))
    ents.append(FoxElectricalPowerSensor(coord))
    ents.append(FoxCopSensor(coord))
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coord, addr):
        super().__init__(coord)
        self._addr = addr
        rec = coord.data.get(addr, {})
        info = rec.get("info", {}) if rec else {}
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_{addr}"
        self._attr_translation_key = f"{prefix}_{addr}"
        try:
            meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        except: meta = {}
        block = (meta.get("block") or info.get("block") or "")
        tab = (meta.get("tab") or info.get("tab") or block)
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        # coordinator stores entry_id via hass.data key; fallback to None -> main
        if not entry_id and hasattr(coord, "_entry_id"):
            entry_id = coord._entry_id
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab, prefix)
        dtype = info.get("type","RAW")
        dc, unit, sc = DTYPE_MAP.get(dtype, (None, info.get("unit") or None, None))
        if dc: self._attr_device_class = dc
        if unit: self._attr_native_unit_of_measurement = unit
        elif info.get("unit"): self._attr_native_unit_of_measurement = info.get("unit")
        if sc: self._attr_state_class = sc
        if dtype in ("TEMP1","TEMP","TEMP05"): self._attr_suggested_display_precision = 1
        elif dtype in ("VOLT","BAR_X10","POWER_KW_X10"): self._attr_suggested_display_precision = 1
        elif dtype == "FLOW_M3H_X100": self._attr_suggested_display_precision = 2
        # v0.3 metadata-aware category
        try:
            meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        except: meta={}
        risk = meta.get("risk")
        if addr in HIDDEN or risk == "blocked":
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            # keep enabled per POPULAR but diagnostic still hides
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
            if addr not in POPULAR_ADDRS:
                self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
        else:
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
            if addr not in POPULAR_ADDRS:
                # Live diagnostic regs are the main operational view — keep visible.
                if tab == "T_Live":
                    self._attr_entity_registry_enabled_default = True
                else:
                    self._attr_entity_category = EntityCategory.DIAGNOSTIC
        # icon: prefer metadata icon, fallback to heat-pump MDI (works even if brand/ PNG missing)
        self._attr_icon = (meta.get("icon") or "mdi:heat-pump") if meta else "mdi:heat-pump"

    @property
    def available(self):
        """Dynamic availability: hide expert entities when expert mode is off."""
        meta = self.coordinator.get_metadata(self._addr) if hasattr(self.coordinator, "get_metadata") else {}
        if meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        return super().available

    @property
    def native_value(self):
        rec = self.coordinator.data.get(self._addr)
        return rec["value"] if rec else None
    @property
    def extra_state_attributes(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec: return {}
        info = rec.get("info",{})
        meta = {}
        try: meta = self.coordinator.get_metadata(self._addr)
        except: pass
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type"), "group": meta.get("group"), "risk": meta.get("risk"), "editable": meta.get("editable"), "min": meta.get("min"), "max": meta.get("max")}

class FoxHeatingCurveTargetSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Heating Curve Target"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve"
    def __init__(self, coord):
        super().__init__(coord)
        prefix = get_device_prefix(coord.entry)
        self._attr_translation_key = f"{prefix}_heating_curve_target"
        self._attr_unique_id = f"{prefix}_heating_curve_target"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        self._attr_device_info = main_device(entry_id, prefix)
        self._hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        self._st = coord.marker("setpoints") if hasattr(coord, "marker") else {}
        self._status = coord.marker("status") if hasattr(coord, "marker") else {}
    @property
    def native_value(self):
        try:
            from .heating_curve import curve_target_for_at
            hc = self._hc.get("addr_single", {}) if isinstance(self._hc, dict) else {}
            at = self.coordinator.data.get(hc.get("at_sensor"), {}).get("value") if hc.get("at_sensor") else None
            if at is None: return None
            v = curve_target_for_at(self.coordinator, float(at))
            return round(v,1) if v is not None else None
        except: return None
    @property
    def extra_state_attributes(self):
        try:
            hc = self._hc.get("addr_single", {}) if isinstance(self._hc, dict) else {}
            st = self._st.get("addr_single", {}) if isinstance(self._st, dict) else {}
            status = self._status.get("addr_single", {}) if isinstance(self._status, dict) else {}
            at = self.coordinator.data.get(hc.get("at_sensor"), {}).get("value") if hc.get("at_sensor") else None
            slope = self.coordinator.data.get(hc.get("slope"), {}).get("value") if hc.get("slope") else None
            offset = self.coordinator.data.get(hc.get("offset"), {}).get("value") if hc.get("offset") else None
            en = self.coordinator.data.get(hc.get("at_comp_en"), {}).get("raw") if hc.get("at_comp_en") else None
            fixed = self.coordinator.data.get(st.get("heating_target"), {}).get("value") if st.get("heating_target") else None
            after = self.coordinator.data.get(hc.get("live_target"), {}).get("value") if hc.get("live_target") else None
            r10 = self.coordinator.data.get(hc.get("r10_min"), {}).get("value") if hc.get("r10_min") else None
            r11 = self.coordinator.data.get(hc.get("r11_max"), {}).get("value") if hc.get("r11_max") else None
            return {"at": at, "slope": slope, "offset": offset, "h36_enable": en, "fixed_r02": fixed, "after_comp_2014": after, "r10_min": r10, "r11_max": r11, "panel": "/api/foxair/heating-curve-panel", "svg": "/api/foxair/heating_curve.svg"}
        except: return {}


# ---------------------------------------------------------------------------
# Computed (derived) sensors: heating power, electrical power, COP.
# These are calculated from raw FoxAir register values rather than read directly.
#
# Heating power uses the classic water-side formula
#     P[W] = (flow_m3h / 3600) * rho * cp * dT
# with an EMA smoother + "hold-last-good" guard on the (flaky) water-flow
# reading, and a hard zero when the compressor is off.
#
# Electrical power used for COP has a configurable source (see Options):
#   - "foxair_register" : the device's own Unit Power register 2054 (/10 kW) —
#                         accurate, no calibration needed (default).
#   - "foxair_v_a"      : V(2062) x I(2057) with user-tunable gain/offset.
#   - "external_meter"  : an external HA power-meter entity.
# COP = heating_power / electrical_power, guarded against standby/garbage values.
# ---------------------------------------------------------------------------

# --- physical constants (water) ---
_RHO = 1000.0     # kg/m^3
_CP = 4186.0      # J/(kg*K)

# --- register addresses (values already pre-scaled by coordinator.scaled) ---
_ADDR_FLOW = 2077       # FLOW_M3H_X100 -> m3/h
_ADDR_T_IN = 2045       # Einlasswassertemperatur (inlet)  TEMP1 -> degC
_ADDR_T_OUT = 2046      # outlet water temp               TEMP1 -> degC
_ADDR_FREQ = 2072       # compressor operation frequency  HZ   -> Hz
_ADDR_VOLT = 2062       # AC input voltage                VOLT -> V
_ADDR_I = 2057          # AC input current (legacy)       RAW  -> raw counts (calibrate!)
_ADDR_UNIT_POWER = 2054 # Unit Power                   POWER_KW_X10 -> /10 kW

# --- defaults for the V/A calibration option ---
_DEFAULT_V_GAIN = 1.0
_DEFAULT_V_OFFSET = 0.0
_DEFAULT_I_GAIN = 0.1   # 2057 raw counts -> ~A (legacy modbus used scale 0.1)
_DEFAULT_I_OFFSET = 0.0

_EMA_ALPHA = 0.3        # flow smoother factor
_FLOW_MIN = 0.3         # m3/h below this the flow signal is meaningless
_FLOW_MAX = 10.0        # m3/h above this the flow signal is clearly bogus
_P_MAX = 20000.0        # W, sanity clamp on heating power
_COP_MAX = 8.0          # COP above this is physically implausible
_ELEC_MIN_FOR_COP = 300.0  # W; ignore COP while essentially idle


def _cval(coord, addr):
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

    EMA smoother + "hold-last-good" guard on the flaky flow reading; forced
    zero when the compressor is off. EMA state lives on the coordinator so it
    survives entity re-setup.
    """
    flow = _cval(coord, _ADDR_FLOW)
    t_in = _cval(coord, _ADDR_T_IN)
    t_out = _cval(coord, _ADDR_T_OUT)
    freq = _cval(coord, _ADDR_FREQ)
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
            ema = ema + _EMA_ALPHA * (flow - ema)
    coord._flow_ema = ema
    if ema < _FLOW_MIN or ema > _FLOW_MAX:
        return None
    dT = t_out - t_in
    if dT <= 0:
        return None
    p = (ema / 3600.0) * _RHO * _CP * dT
    if not (0 < p < _P_MAX):
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
        v_raw = _cval(coord, _ADDR_VOLT)
        i_raw = _cval(coord, _ADDR_I)
        if v_raw is None or i_raw is None:
            return None
        v_gain = float((options or {}).get("v_gain", _DEFAULT_V_GAIN))
        v_off = float((options or {}).get("v_offset", _DEFAULT_V_OFFSET))
        i_gain = float((options or {}).get("i_gain", _DEFAULT_I_GAIN))
        i_off = float((options or {}).get("i_offset", _DEFAULT_I_OFFSET))
        v = (v_raw + v_off) * v_gain
        i = (i_raw + i_off) * i_gain
        if v <= 0 or i <= 0:
            return None
        return v * i
    # default: device Unit Power register (/10 kW -> W)
    p = _cval(coord, _ADDR_UNIT_POWER)
    if p is None:
        return None
    w = p * 1000.0
    return w if w >= 0 else None


class FoxComputedSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord):
        super().__init__(coord)
        prefix = get_device_prefix(coord.entry)
        entry_id = getattr(coord, "_entry_id", None) or (
            getattr(coord, "config_entry", None)
            and coord.config_entry.entry_id
        )
        self._attr_device_info = main_device(entry_id, prefix)
        self._prefix = prefix

    @property
    def _opts(self):
        return self.coordinator.entry.options


class FoxHeatingPowerSensor(FoxComputedSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:radiator"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._prefix}_heating_power"
        self._attr_translation_key = f"{self._prefix}_heating_power"

    @property
    def native_value(self):
        p = compute_heating_power(self.coordinator)
        return None if p is None else round(p, 1)

    @property
    def extra_state_attributes(self):
        try:
            flow = _cval(self.coordinator, _ADDR_FLOW)
            freq = _cval(self.coordinator, _ADDR_FREQ)
            ema = getattr(self.coordinator, "_flow_ema", 0.0)
            return {
                "flow_raw_m3h": flow,
                "flow_smoothed_m3h": round(ema, 3),
                "compressor_freq_hz": freq,
            }
        except Exception:
            return {}


class FoxElectricalPowerSensor(FoxComputedSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._prefix}_electrical_power"
        self._attr_translation_key = f"{self._prefix}_electrical_power"

    @property
    def native_value(self):
        p = compute_electrical_power(self.coordinator, self._opts)
        return None if p is None else round(p, 1)

    @property
    def extra_state_attributes(self):
        source = (self._opts or {}).get("elec_source", "foxair_register")
        return {"source": source}


class FoxCopSensor(FoxComputedSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sigma"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._prefix}_cop"
        self._attr_translation_key = f"{self._prefix}_cop"

    @property
    def native_value(self):
        hp = compute_heating_power(self.coordinator)
        if hp is None:
            return None
        ep = compute_electrical_power(self.coordinator, self._opts)
        if ep is None or ep <= _ELEC_MIN_FOR_COP:
            return None
        cop = hp / ep
        if 0 < cop <= _COP_MAX:
            return round(cop, 2)
        return None
