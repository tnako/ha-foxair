"""Heating curve helper for v0.3.3+ — fixed vs weather-compensated.

Fixed: target = R02 (heating_target marker); active_control() picks the setpoint per H25/mode
Curve: target(AT) = offset - slope * AT  (reference AT = 0), clamped [R10/R11] + envelope R31/R34

Slope (heat_curve.marker slope) RAW -> /10 => 0.0..3.0, Offset TEMP1 -> /10 => -10..10
Enable (at_comp_en marker) H36 0/1 (select) — 1 = curve
"""
from typing import Optional

def calc_curve_target(at_c: float, slope: float, offset: float, base: float = 0.0) -> float:
    """Linear weather compensation.

    FoxAir/Phnix formula (reference point is AT = 0):
        target(AT) = offset - slope * AT
    i.e. flow at the design outside temperature 0 °C equals `offset`,
    and flow drops by `slope` per 1 °C of AT rise.
    `base` is kept for call-compatibility (defaults to 0).
    """
    try:
        return float(offset) - float(slope) * float(at_c)
    except Exception:
        return 0.0

def clamp(v: float, lo: Optional[float], hi: Optional[float]) -> float:
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v

def mode_values(coord) -> dict:
    """1012 operating-mode raw values by name from the status marker."""
    try:
        return coord.marker("status").get("mode_values") or {}
    except Exception:
        return {}

def is_cooling(coord) -> bool:
    """True when 1012 selects a cooling mode (cooling or cooling + DHW)."""
    try:
        mv = mode_values(coord)
        rec = coord.data.get((coord.marker("status").get("addr_single") or {}).get("mode"))
        return bool(rec) and rec.get("raw") in (mv.get("cooling"), mv.get("cooling_dhw"))
    except Exception:
        return False

def control_source(coord) -> dict:
    """Active H25 control source entry from the control_source marker, or {}."""
    try:
        m = coord.marker("control_source") if hasattr(coord, "marker") else {}
        if not isinstance(m, dict):
            return {}
        by_value = m.get("by_value") or {}
        selector = (m.get("addr_single") or {}).get("selector")
        rec = (getattr(coord, "data", None) or {}).get(selector) if selector else None
        raw = rec.get("raw") if rec else None
        if raw is not None:
            try:
                raw = str(int(raw))
            except (TypeError, ValueError):
                raw = str(raw)
        return by_value.get(raw) or by_value.get(str(m.get("default"))) or {}
    except Exception:
        return {}

def active_control(coord) -> dict:
    """What the unit regulates right now, from H25 (source), 1012 (mode) and H36 (curve).

    current/target: sensor and setpoint addrs; curve: the H36 curve drives the target
    (water source while heating only); min/max/start/stop: limit and hysteresis addrs
    for the active side, from the source entry when it has its own setpoint.
    """
    try:
        src = control_source(coord)
        cooling = is_cooling(coord)
        side = "cooling" if cooling else "heating"
        own = src.get("target")
        regs = src if own else (coord.marker("setpoints").get("addr_single") or {})
        hc = coord.marker("heat_curve").get("addr_single") or {}
        h36 = (coord.data.get(hc.get("at_comp_en")) or {}).get("raw")
        return {
            "source": src.get("key"),
            "own_target": bool(own),
            "cooling": cooling,
            "curve": h36 == 1 and not cooling and not own,
            "current": src.get("current") or (coord.marker("status").get("addr_single") or {}).get("outlet_water_temp"),
            "target": own or regs.get(f"{side}_target"),
            **{k: regs.get(f"{side}_{k}") for k in ("min", "max", "start", "stop")},
        }
    except Exception:
        return {}

def curve_target_for_at(coord, at_c: float) -> Optional[float]:
    """Compute curve target for given AT using coordinator markers/metadata/live values."""
    try:
        m = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        hc = m.get("addr_single", {}) if isinstance(m, dict) else {}
        slope_addr = hc.get("slope")
        off_addr = hc.get("offset")
        slope_rec = coord.data.get(slope_addr) if slope_addr else None
        off_rec = coord.data.get(off_addr) if off_addr else None
        if slope_rec is None or off_rec is None:
            return None
        # slope is already scaled by coordinator (DIGI5 -> /10)
        slope = slope_rec.get("value", 0)
        offset = off_rec.get("value", 0)
        if slope > 5:
            slope = slope / 10.0
        target = calc_curve_target(at_c, slope, offset)
        # clamp to R10/R11 envelope
        r10_addr = hc.get("r10_min")
        r11_addr = hc.get("r11_max")
        r10 = coord.data.get(r10_addr) if r10_addr else None
        r11 = coord.data.get(r11_addr) if r11_addr else None
        lo = r10["value"] if r10 else 20
        hi = r11["value"] if r11 else 60
        return max(lo, min(hi, target))
    except Exception:
        return None
