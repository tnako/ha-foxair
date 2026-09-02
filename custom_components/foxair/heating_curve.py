"""Heating curve helper for v0.3.3+ — fixed vs weather-compensated.

Fixed: target = R02 (heating_target marker)
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
    if lo is not None and v < lo: return lo
    if hi is not None and v > hi: return hi
    return v

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
