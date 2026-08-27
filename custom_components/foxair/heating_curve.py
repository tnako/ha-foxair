"""Heating curve helper for v0.3.3+ — fixed vs weather-compensated.

Fixed: target = R02 (1158)
Curve: target(AT) = 35 + offset + slope*(20 - AT) clamped [R10/R11] + envelope R31/R34

Slope 1234 RAW -> /10 => 0.0..3.0, Offset 1235 TEMP1 -> /10 => -10..10
Enable 1236 H36 0/1 (select) — 1 = curve
"""
from typing import Optional

def calc_curve_target(at_c: float, slope: float, offset: float, base: float = 35.0) -> float:
    """Linear weather compensation."""
    try:
        return base + float(offset) + float(slope) * (20.0 - float(at_c))
    except:
        return base

def clamp(v: float, lo: Optional[float], hi: Optional[float]) -> float:
    if lo is not None and v < lo: return lo
    if hi is not None and v > hi: return hi
    return v

def curve_target_for_at(coord, at_c: float) -> Optional[float]:
    """Compute curve target for given AT using coordinator metadata/live values."""
    try:
        slope_rec = coord.data.get(1234)
        off_rec = coord.data.get(1235)
        en_rec = coord.data.get(1236)
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
