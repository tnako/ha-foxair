"""Heating curve helper for v0.3.3+ — fixed vs weather-compensated.

Fixed: target = R02 (heating_target marker); active_control() picks the setpoint per H25/mode
Curve: target(AT) = offset - slope * AT  (reference AT = 0), clamped [R10/R11] + envelope R31/R34

Points (V3.5, H36 = 2): setpoints at fixed AT (heat_curve.points), linear interpolation between them

Slope (heat_curve.marker slope) RAW -> /10 => 0.0..3.0, Offset TEMP1 -> /10 => -10..10
Enable (at_comp_en marker) H36 0/1/2 (select) — 1 = linear curve, 2 = 7-point curve
"""
from typing import Optional


def curve_mode(coord) -> str:
    """'off', 'linear' or 'points' from H36 and heat_curve.mode_values."""
    try:
        hc = coord.marker("heat_curve")
        raw = (coord.data.get((hc.get("addr_single") or {}).get("at_comp_en")) or {}).get("raw")
        modes = hc.get("mode_values") or {"off": 0, "linear": 1}
        return next((k for k, v in modes.items() if v == raw), "off")
    except Exception:
        return "off"


def curve_points(coord) -> Optional[list]:
    """Sorted [(AT, setpoint)] of the 7-point curve, None until every point is read."""
    try:
        pts = coord.marker("heat_curve").get("points") or {}
        out = []
        for at, addr in pts.items():
            v = (coord.data.get(addr) or {}).get("value")
            if v is None:
                return None
            out.append((float(at), float(v)))
        return sorted(out) or None
    except Exception:
        return None


def calc_points_target(at_c: float, points: list) -> float:
    """Linear interpolation between curve points, held flat beyond the outer points."""
    at_c = float(at_c)
    if at_c <= points[0][0]:
        return points[0][1]
    for (a0, v0), (a1, v1) in zip(points, points[1:]):
        if at_c <= a1:
            return v0 + (v1 - v0) * (at_c - a0) / (a1 - a0)
    return points[-1][1]

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
        mode = curve_mode(coord)
        curve = mode != "off" and not cooling and not own
        return {
            "source": src.get("key"),
            "own_target": bool(own),
            "cooling": cooling,
            "curve": curve,
            "curve_mode": mode if curve else "off",
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
        points = curve_points(coord) if curve_mode(coord) == "points" else None
        if points:
            target = calc_points_target(at_c, points)
        else:
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


def _marker_value(coord, marker_name, key, field="value"):
    addr = ((coord.marker(marker_name) or {}).get("addr_single") or {}).get(key)
    return ((getattr(coord, "data", None) or {}).get(addr) or {}).get(field) if addr else None


def outdoor_source(coord) -> Optional[str]:
    """'external', 'fallback' (external selected but invalid, T04 used) or 'internal'; None before 1463 is read."""
    try:
        sel = _marker_value(coord, "outdoor_sensor", "selector", "raw")
        if sel is None:
            return None
        if sel != 1:
            return "internal"
        ext = _marker_value(coord, "outdoor_sensor", "external")
        m = coord.marker("outdoor_sensor")
        fault = _marker_value(coord, "outdoor_sensor", "fault_word", "raw")
        if fault is not None and int(fault) >> int(m.get("fault_bit", 7)) & 1:
            return "fallback"
        limit = m.get("invalid_above", 150.0)
        return "external" if ext is not None and float(ext) < float(limit) else "fallback"
    except Exception:
        return None


def summer_cutoff(coord) -> Optional[dict]:
    """{'active', 'threshold', 'release', 'delay', 'enabled'} of the V3.5 heating/summer cut-off, None when not read."""
    try:
        m = coord.marker("summer_cutoff") or {}
        threshold = _marker_value(coord, "summer_cutoff", "threshold")
        delay = _marker_value(coord, "summer_cutoff", "delay")
        status = _marker_value(coord, "summer_cutoff", "status", "raw")
        if threshold is None or delay is None:
            return None
        active = None if status is None else bool(int(status) >> int(m.get("status_bit", 4)) & 1)
        return {"active": active, "threshold": float(threshold),
                "release": float(threshold) - float(m.get("hysteresis", 3.0)),
                "delay": int(delay), "enabled": int(delay) > 0}
    except Exception:
        return None
