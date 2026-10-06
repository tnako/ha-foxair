from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from .const import POPULAR_ADDRS, SENSOR_HIDDEN_ADDRS, device_for_addr, device_for_block, main_device, entity_sort_key, get_device_prefix, get_slave_id, bind_device_info, entity_suffix, dependency_met
from .computed import (compute_heating_power, compute_electrical_power, compute_cop,
                       compute_cop_mode, active_mode, _cval)
from .efficiency_runtime import marker_addrs

# Build DTYPE_MAP lazily from DTYPE_SPEC: const globals are populated by
# apply_config() at coordinator load (in-place), so resolve at entity-setup
# time, not at import time (import happens before config load inside HA).
def _dtype_map():
    from . import const as _const
    spec = _const.DTYPE_SPEC or {}
    out = {}
    for dtype, s in spec.items():
        try:
            device_class = getattr(SensorDeviceClass, s["device_class"].upper()) if s["device_class"] else None
            state_class = getattr(SensorStateClass, s["state_class"].upper()) if s["state_class"] else None
        except Exception:
            device_class, state_class = None, None
        out[dtype] = (device_class, s.get("unit"), state_class)
    return out

# Sensor addrs with no standalone entity (shown via computed sensors instead).
# From foxair_config.json sensor_hidden_addrs — never hardcoded here: not
# every addr exists on every firmware, and literals rot silently.
HIDDEN = SENSOR_HIDDEN_ADDRS

async def async_setup_entry(hass, entry, add_entities):
    coord = entry.runtime_data
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
        # BITFIELD registers with a bit_map are expanded into per-bit
        # binary_sensors — a raw decimal sensor would be meaningless
        if (meta.get("type") or "").upper() == "BITFIELD":
            _rm = (getattr(coord, "_regmap", None) or {}).get(str(addr), {})
            if _rm.get("bit_map"):
                continue
        if meta.get("editable") and meta.get("platform") in ("number", "select", "time"):
            continue
        ents.append(FoxSensor(coord, addr))
    # computed (derived) sensors: heating power, electrical power, COP,
    # per-mode energy meters (heating/cooling/dhw + electrical), per-mode COPs
    ents.append(FoxHeatingPowerSensor(coord))
    ents.append(FoxElectricalPowerSensor(coord))
    ents.append(FoxCopSensor(coord))
    for _mode in ("heating", "cooling", "dhw", "defrost"):
        ents.append(FoxEnergySensor(coord, _mode))
    ents.append(FoxElectricalEnergySensor(coord))
    for _mode in ("cooling", "dhw"):
        ents.append(FoxModeCopSensor(coord, _mode))
    if getattr(coord, "efficiency", None) is not None:
        ents.extend([FoxEfficiencyIndexSensor(coord), FoxExpectedCopSensor(coord),
                     FoxEfficiencySettingsSensor(coord), FoxEfficiencyFindingSensor(coord),
                     FoxEfficiencyNextStepSensor(coord), FoxEfficiencyNextChangeSensor(coord),
                     FoxEfficiencyDailySensor(coord), FoxDefrostSensor(coord)])
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    # has_entity_name=True is REQUIRED for translation_key-based names to
    # resolve (HA _name_internal only translates when has_entity_name is set).
    _attr_has_entity_name = True
    def __init__(self, coord, addr):
        super().__init__(coord)
        self._addr = addr
        rec = coord.data.get(addr, {})
        info = rec.get("info", {}) if rec else {}
        prefix = get_device_prefix(coord.entry)
        suffix = entity_suffix(coord, addr)
        self._attr_unique_id = f"{prefix}_{suffix}"
        # HA 2026.9 ignores _attr_suggested_object_id (computed from name now);
        # the supported id override is a pre-set entity_id (no device prefix).
        self.entity_id = f"sensor.{prefix}_{suffix}"
        self._attr_translation_key = f"foxair_{suffix}"
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
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, block, entry_id, tab, prefix, slave_id, host, port))
        dtype = info.get("type","RAW")
        dc, unit, sc = _dtype_map().get(dtype, (None, info.get("unit") or None, None))
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
        # dep not polled (e.g. expert-gated H27 for a non-expert user):
        # can't prove disabled, so keep showing (missing=True).
        if not dependency_met(self.coordinator, m2, missing=True):
            return False
        try:
            if hasattr(self.coordinator, "is_stale") and self.coordinator.is_stale(self._addr):
                return False
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
        self._prefix = get_device_prefix(coord.entry)
        entry_id = getattr(coord, "_entry_id", None) or (
            getattr(coord, "config_entry", None)
            and coord.config_entry.entry_id
        )
        slave_id = get_slave_id(coord.entry)
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, main_device(entry_id, self._prefix, slave_id))

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
        self.entity_id = f"sensor.{self._prefix}_heating_power"
        self._attr_translation_key = "foxair_heating_power"  # stable key, translations only under foxair_

    @property
    def native_value(self):
        p = compute_heating_power(self.coordinator)
        return None if p is None else round(p, 1)

    @property
    def extra_state_attributes(self):
        try:
            from .computed import _cval, _ADDR_FLOW, _ADDR_FREQ
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
        self.entity_id = f"sensor.{self._prefix}_electrical_power"
        self._attr_translation_key = "foxair_electrical_power"  # stable key, translations only under foxair_

    @property
    def native_value(self):
        p = compute_electrical_power(self.coordinator, self._opts)
        return None if p is None else round(p, 1)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        meter = (self._opts or {}).get("external_meter_entity") or ""
        if meter.strip():
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [meter.strip()], self._async_meter_changed
                )
            )

    async def _async_meter_changed(self, _event):
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        source = (self._opts or {}).get("elec_source", "foxair_register")
        return {"source": source}


class FoxCopSensor(FoxComputedSensor):
    """Overall COP — counts while the unit produces heat (heating/defrost).

    Historically the only COP entity; now the heating member of the
    heating/cooling/dhw COP trio (uid `foxair_cop` kept stable).
    """
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sigma"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._prefix}_cop"
        self.entity_id = f"sensor.{self._prefix}_cop"
        self._attr_translation_key = "foxair_cop"  # stable key, translations only under foxair_

    @property
    def native_value(self):
        return compute_cop(self.coordinator, self._opts)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        meter = (self._opts or {}).get("external_meter_entity") or ""
        if meter.strip():
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [meter.strip()], self._async_meter_changed
                )
            )

    async def _async_meter_changed(self, _event):
        self.async_write_ha_state()


class FoxModeCopSensor(FoxCopSensor):
    """Per-mode COP (cooling/dhw): mode thermal power / total electrical power.

    Shows a value only while the unit's run status (2012) reports that
    mode, so the number is always a real operating COP, never a leftover.
    """

    def __init__(self, coord, mode):
        super().__init__(coord)
        self._mode = mode
        self._attr_unique_id = f"{self._prefix}_cop_{mode}"
        self.entity_id = f"sensor.{self._prefix}_cop_{mode}"
        self._attr_translation_key = f"foxair_cop_{mode}"

    @property
    def native_value(self):
        return compute_cop_mode(self.coordinator, self._opts, self._mode)


class FoxEnergySensor(FoxComputedSensor, RestoreEntity):
    """Per-mode thermal energy (kWh), integrated in the coordinator.

    total_increasing + device_class energy -> feeds the HA Energy
    dashboard. Counters live in coord.energy_kwh and are restored from
    the last written state on HA restart, so each meter continues where
    it stopped instead of restarting at 0. Counters persist across
    integration reloads too (they live on the coordinator, which
    survives an entity reload); they reset only when the config entry
    is deleted or the counter battery of history is manually reset.
    """
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:fire"  # cooling/dhw override below

    _ICONS = {"heating": "mdi:fire", "cooling": "mdi:snowflake",
              "dhw": "mdi:water-boiler", "defrost": "mdi:snowflake-melt"}

    def __init__(self, coord, mode):
        super().__init__(coord)
        self._mode = mode
        self._attr_icon = self._ICONS[mode]
        self._attr_unique_id = f"{self._prefix}_energy_{mode}"
        self.entity_id = f"sensor.{self._prefix}_energy_{mode}"
        self._attr_translation_key = f"foxair_energy_{mode}"

    async def async_added_to_hass(self) -> None:
        """Restore the counter from HA's last state after a restart.

        The restored kWh is written back into the coordinator bucket so
        accumulation continues from where the previous run stopped. The
        accumulator's first poll after restart only measures from now on
        (its _energy_last_ts starts at None), so nothing is double-counted
        for the offline period.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            try:
                restored = float(last.state)
            except (TypeError, ValueError):
                return
            if restored <= 0:
                return
            bucket = getattr(self, "_mode", None)
            if not bucket:
                return
            ek = getattr(self.coordinator, "energy_kwh", None)
            if ek is None:
                return
            ek[bucket] = max(ek.get(bucket, 0.0), restored)

    @property
    def native_value(self):
        val = getattr(self.coordinator, "energy_kwh", {}).get(self._mode, 0.0)
        return round(val, 3)

    @property
    def extra_state_attributes(self):
        attrs = {"mode": self._mode}
        try:
            active = active_mode(self.coordinator)
        except Exception:
            active = None
        if active is not None:
            attrs["active_mode"] = active
        return attrs


class FoxElectricalEnergySensor(FoxEnergySensor):
    """Electrical energy consumed by the heat pump (kWh).

    Integrates the electrical draw (T54 / external meter / V*A fallback)
    whenever any power is reported, regardless of mode. Standby and
    pump-only draw are included; the per-mode thermal buckets are not
    affected by this sensor.
    """
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coord):
        super().__init__(coord, "heating")
        self._mode = "electrical"  # coordinator bucket key
        self._attr_icon = "mdi:transmission-tower"  # after super(): it sets mode icon
        self._attr_unique_id = f"{self._prefix}_energy_electrical"
        self.entity_id = f"sensor.{self._prefix}_energy_electrical"
        self._attr_translation_key = "foxair_energy_electrical"

    @property
    def native_value(self):
        val = getattr(self.coordinator, "energy_kwh", {}).get("electrical", 0.0)
        return round(val, 3)


class FoxEfficiencySensor(FoxComputedSensor):
    """Efficiency analyser output, on the Efficiency sub-device."""
    _key = ""

    def __init__(self, coord):
        super().__init__(coord)
        entry_id = coord.entry.entry_id
        self._attr_unique_id = f"{self._prefix}_efficiency_{self._key}"
        self.entity_id = f"sensor.{self._prefix}_efficiency_{self._key}"
        self._attr_translation_key = f"foxair_efficiency_{self._key}"
        self._attr_device_info = bind_device_info(
            getattr(coord, "hass", None), entry_id,
            device_for_block("EFF", entry_id, None, self._prefix, get_slave_id(coord.entry)))

    @property
    def _an(self):
        return self.coordinator.efficiency.analyser


class FoxEfficiencyIndexSensor(FoxEfficiencySensor):
    """Last 24 h actual COP as % of the baseline model's prediction for the same weather and load."""
    _key = "index"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_value(self):
        r = self._an.recent
        return None if not r else r["index_pct"]

    @property
    def extra_state_attributes(self):
        an = self._an
        groups = {an.describe(fp): g for fp, g in an.groups.items()}
        attrs = {"baseline": an.baseline_fp, "buckets": len(an.buckets),
                 "recent_buckets": (an.recent or {}).get("buckets", 0), "groups": groups,
                 "daily_groups": {an.describe(fp): g for fp, g in an.day_groups.items()}}
        if an.model:
            attrs["model_fit_error_pct"] = an.model["mape_pct"]
            attrs["model_days"] = an.model["days"]
        return attrs


class FoxExpectedCopSensor(FoxEfficiencySensor):
    """COP the baseline model expects right now (same compressor Hz, outdoor and flow temperature)."""
    _key = "expected_cop"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self):
        c = self.coordinator
        if compute_cop(c, self._opts) is None:
            return None
        a = marker_addrs(c)
        v = self._an.expected_cop(*(_cval(c, a[k]) if a[k] else None for k in ("hz", "t_out", "t_flow")))
        return None if v is None else round(v, 2)


class FoxEfficiencySettingsSensor(FoxEfficiencySensor):
    """Current EEV settings group: 'baseline' or the parameters that differ from it."""
    _key = "settings"

    @property
    def native_value(self):
        an = self._an
        if not an.current:
            return None
        return an.describe(an.current_fp())[:255]

    @property
    def extra_state_attributes(self):
        an = self._an
        fp = an.current_fp() if an.current else None
        return {"fingerprint": fp, "settings": dict(an.current),
                "baseline_settings": an.settings.get(an.baseline_fp or "", {}),
                "result": an.groups.get(fp or "", {}), "daily_result": an.day_groups.get(fp or "", {})}


class FoxEfficiencyFindingSensor(FoxEfficiencySensor):
    """Headline finding of the analyser (enum, translated)."""
    _key = "finding"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["collecting", "ok", "short_cycling", "superheat_off_target", "superheat_costs",
                     "fan_at_max", "defrost_on_timer"]

    @property
    def native_value(self):
        return self._an.hint_list[0]

    @property
    def extra_state_attributes(self):
        return {"all": list(self._an.hint_list), "superheat_target": self._an.sh_target}


def _fmt(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _advice_message(adv: dict) -> str:
    """One-line English summary of the advice for dashboards and notifications."""
    a, p, f, t = adv.get("action"), adv.get("param"), adv.get("from"), adv.get("to")
    days = adv.get("days_left")
    when = adv.get("not_before")
    if a == "change":
        return f"Change {p} from {_fmt(f)} to {_fmt(t)}, then keep it for at least {days} heating days"
    if a == "revert":
        return f"Set {p} back from {f} to {t} ({adv.get('reason')})" if p else "Restore the baseline settings"
    if a == "accept":
        return f"Keep {p}={t} and press Set EEV baseline ({adv.get('delta_pct')} % vs baseline)"
    if a == "keep" and adv.get("reason") == "settling_after_change" and when:
        from datetime import datetime
        return f"Wait: no change before {datetime.fromtimestamp(when).strftime('%Y-%m-%d %H:%M')}"
    if a == "keep":
        return f"Keep the current settings for {days} more heating day(s)"
    if a == "collecting":
        return f"Collecting the baseline: {days} more heating day(s) needed"
    if a == "wait_heating":
        nxt = f", then change {p} from {f} to {t}" if p and t is not None else ""
        return f"Wait for heating demand (about 1 h of steady heating a day){nxt}"
    if a == "check_curve":
        return "Short cycling: fix the heating curve or hysteresis before EEV tests"
    if a == "done":
        return "All planned EEV steps are tested"
    return "Waiting for EEV settings"


class FoxEfficiencyNextStepSensor(FoxEfficiencySensor):
    """What to do next: change, keep, revert, accept, wait (enum, translated)."""
    _key = "next_step"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["collecting", "keep", "change", "revert", "accept", "wait_heating", "check_curve", "done", "none"]

    @property
    def native_value(self):
        return self._an.advice.get("action", "none")

    @property
    def extra_state_attributes(self):
        from datetime import datetime, timezone
        adv = dict(self._an.advice)
        if adv.get("not_before"):
            adv["not_before"] = datetime.fromtimestamp(adv["not_before"], timezone.utc).isoformat()
        log = []
        for c in self._an.changes[-10:]:
            log.append({"time": datetime.fromtimestamp(c["t"], timezone.utc).isoformat(), "kind": c.get("kind"),
                        "diff": c.get("diff"), "verdict": (self._an.groups.get(c.get("to") or "") or {}).get("verdict")})
        return {**adv, "message": _advice_message(self._an.advice), "changes": log}


class FoxEfficiencyNextChangeSensor(FoxEfficiencySensor):
    """Earliest time the next EEV change is allowed (last change + 24 h); unknown when no change is pending."""
    _key = "next_change"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        from datetime import datetime, timezone
        t = self._an.advice.get("not_before")
        return None if not t else datetime.fromtimestamp(t, timezone.utc)

    @property
    def extra_state_attributes(self):
        from datetime import datetime, timezone
        last = self._an.last_change()
        return {"last_change": None if not last else datetime.fromtimestamp(last["t"], timezone.utc).isoformat(),
                "last_diff": None if not last else last.get("diff")}


class FoxEfficiencyDailySensor(FoxEfficiencySensor):
    """Whole-day COP (heat out / electricity in, defrost, cycling and standby included) of the last full day."""
    _key = "daily_cop"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self):
        d = self._an.last_day()
        return None if not d else d["cop"]

    @property
    def extra_state_attributes(self):
        from datetime import datetime, timezone
        d = self._an.last_day() or {}
        if d:
            d = {**d, "day": datetime.fromtimestamp(d["day"] * 86400, timezone.utc).date().isoformat()}
        m = self._an.day_model
        return {**d, "days_recorded": len(self._an.days),
                "model_fit_error_pct": None if not m else m["mape_pct"]}


class FoxDefrostSensor(FoxEfficiencySensor):
    """Defrost cycles in the last 24 h, with duration, interval and energy of the recent ones."""
    _key = "defrosts"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        import time as _t
        return sum(1 for e in self._an.defrosts if _t.time() - e["t"] <= 86400)

    @property
    def extra_state_attributes(self):
        import time as _t
        from datetime import datetime, timezone
        from .efficiency import defrost_summary
        an = self._an
        summ = defrost_summary(an.defrosts, _t.time(), an.current.get("D03"))
        last = [{**e, "t": datetime.fromtimestamp(e["t"], timezone.utc).isoformat()} for e in an.defrosts[-5:]]
        return {**summ, "recent": last, "recorded": len(an.defrosts)}
