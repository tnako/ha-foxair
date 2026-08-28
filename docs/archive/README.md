# Archive

Historic reviews from **v0.3** — kept for reference, not reflecting current **0.4.3+** `modbus-connection` architecture.

- `ARCHITECTURE_REVIEW_v0.3.md` — snapshot at ~573 registers / 12 `POLL_BLOCKS` / `AsyncModbusTcpClient`. Now: 591 registers, `foxair-modbus` `Component` pooled reads (`max_span=65`), owned `ModbusConnection` via `modbus_connection[pymodbus]`. Numbers in that review (573→591, 12 blocks→pooled, TIME_HHMM orphan) are outdated.
- `SECURITY_REVIEW_v0.3.md` — hardening checklist for `parse_range`, null limits, expert gate. Most items fixed in 0.4.x (`RANGE_OVERRIDES` for 1234, fallbacks, `math.isfinite` guard, per-type limits). Kept as checklist for 0.5.

For current architecture see [README.md](../../README.md) + [ROADMAP.md](../ROADMAP.md) + [DEBUG.md](../DEBUG.md). New reviews should be added here with version suffix.
