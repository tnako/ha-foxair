from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import POPULAR_ADDRS, device_for_addr, main_device, entity_sort_key, DTYPE_SPEC, get_device_prefix

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
        # honor metadata hidden/blocked
        meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        if meta.get("risk") == "blocked" or meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        # expert-gated (whole expert blocks + dangerous) sensors: skip unless expert on
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        if meta.get("editable") and meta.get("platform") in ("number", "select", "time"):
            continue
        ents.append(FoxSensor(coord, addr))
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
        except Exception:
            meta = {}
        block = (meta.get("block") or info.get("block") or "")
        tab = (meta.get("tab") or info.get("tab") or block)
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        # coordinator stores entry_id via hass.data key; fallback to None -> main
        if not entry_id and hasattr(coord, "_entry_id"):
            entry_id = coord._entry_id
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab, prefix)
        dtype = info.get("type","RAW")
        dc, unit, sc = DTYPE_MAP.get(dtype, (None, info.get("unit") or None, None))
        if dc:
            self._attr_device_class = dc
        if unit:
            self._attr_native_unit_of_measurement = unit
        elif info.get("unit"):
            self._attr_native_unit_of_measurement = info.get("unit")
        if sc and meta.get("format") != "firmware":
            self._attr_state_class = sc
        if dtype in ("TEMP1","TEMP","TEMP05"):
            self._attr_suggested_display_precision = 1
        elif dtype in ("VOLT","BAR_X10","POWER_KW_X10"):
            self._attr_suggested_display_precision = 1
        elif dtype == "FLOW_M3H_X100":
            self._attr_suggested_display_precision = 2
        # v0.3 metadata-aware category
        try:
            meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        except Exception:
            meta = {}
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
        # Registry-driven enum sensor: read-only DIGI1/RAW with value_map gets ENUM
        if meta.get("has_value_map"):
            try:
                vm = None
                # _regmap loaded by coordinator
                regmap = getattr(coord, "_regmap", {}) if hasattr(coord, "_regmap") else {}
                vm = (regmap.get(str(addr)) or {}).get("value_map")
            except Exception:
                vm = None
            if vm:
                self._attr_device_class = SensorDeviceClass.ENUM
                self._attr_options = [str(k) for k in vm.keys()]
                if hasattr(self, "_attr_state_class"):
                    try:
                        delattr(self, "_attr_state_class")
                    except Exception:
                        pass
                self._attr_state_class = None
        # icon: prefer metadata icon, fallback to heat-pump MDI (works even if brand/ PNG missing)
        self._attr_icon = (meta.get("icon") or "mdi:heat-pump") if meta else "mdi:heat-pump"

    @property
    def available(self):
        """Dynamic availability: expert gating + registry depends_on."""
        meta = self.coordinator.get_metadata(self._addr) if hasattr(self.coordinator, "get_metadata") else {}
        if meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        try:
            m2 = self.coordinator.get_metadata(self._addr) if hasattr(self.coordinator, "get_metadata") else {}
        except Exception:
            m2 = {}
        dep = m2.get("depends_on")
        if dep is not None:
            try:
                rec = self.coordinator.data.get(int(dep))
                if not rec:
                    return False
                raw = rec.get("raw")
                if raw is None:
                    raw = rec.get("value")
                if raw is None:
                    return False
                s = str(raw).strip().lower()
                if s in ("0", "0.0", "off", "no", "false", ""):
                    return False
                try:
                    if float(raw) == 0:
                        return False
                except Exception:
                    pass
            except Exception:
                pass
        return super().available

    @property
    def native_value(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return None
        v = rec["value"]
        # Firmware version format: raw is major*10+minor (e.g. 33 = v3.3)
        meta = self.coordinator.get_metadata(self._addr) if hasattr(self.coordinator, "get_metadata") else {}
        if meta.get("format") == "firmware" and isinstance(v, (int, float)):
            major = int(v) // 10
            minor = int(v) % 10
            return f"v{major}.{minor}"
        # Registry-driven enum: return raw key as string for state translation
        meta2 = self.coordinator.get_metadata(self._addr) if hasattr(self.coordinator, "get_metadata") else {}
        if meta2.get("has_value_map"):
            try:
                return str(int(float(v)))
            except Exception:
                return str(v)
        return v
    @property
    def extra_state_attributes(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return {}
        info = rec.get("info",{})
        meta = {}
        try:
            meta = self.coordinator.get_metadata(self._addr)
        except Exception:
            pass
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type"), "group": meta.get("group"), "risk": meta.get("risk"), "editable": meta.get("editable"), "min": meta.get("min"), "max": meta.get("max")}


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
        self._attr_translation_key = "foxair_heating_power"  # stable key, translations only under foxair_

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
        self._attr_translation_key = "foxair_electrical_power"  # stable key, translations only under foxair_

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
        self._attr_translation_key = "foxair_cop"  # stable key, translations only under foxair_

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
