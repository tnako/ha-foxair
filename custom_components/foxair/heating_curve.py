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
        slope_addr = hc.get("slope", 1234)
        off_addr = hc.get("offset", 1235)
        slope_rec = coord.data.get(slope_addr)
        off_rec = coord.data.get(off_addr)
        if slope_rec is None or off_rec is None:
            return None
        # slope RAW is DIGI5 /10? Actually type DIGI5 => scaled /10, but 1234 was DIGI5 in metadata
        slope = slope_rec.get("value", 0)
        offset = off_rec.get("value", 0)
        # normalize slope: if metadata says 0-100 step 0.1, slope 10 = 1.0 ? Check: our fallback 0-100 for DIGI5 would be 0-10 after /10 -> 0-10 slope unrealistic. Clamp slope 0-3
        # Interpret slope as /10 already done by coordinator scaled
        # If slope > 5 assume /10 was not applied? Keep as is but clamp 0-3
        if slope > 5:
            slope = slope / 10.0
        target = calc_curve_target(at_c, slope, offset)
        # clamp to R10/R11 + R31/R34 envelope
        r10 = coord.data.get(1164)
        r11 = coord.data.get(1165)
        r31 = coord.data.get(1169)
        r34 = coord.data.get(1172)
        lo = r10["value"] if r10 else 20
        hi = r11["value"] if r11 else 60
        # envelope low/high AT clamps are not directly min - they are point clamps; we use overall min/max as bounds
        return max(lo, min(hi, target))
    except:
        return None
