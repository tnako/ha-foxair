# Debug / Diagnostics

## Logger
Add to configuration.yaml:
```yaml
logger:
  logs:
    custom_components.foxair: debug
    pymodbus: debug
```

## Diagnostics
Settings -> Devices -> FoxAir -> Download diagnostics. Contains: host/port, poll blocks, last raw values per block (no secrets), error counters, coordinator latency.

## Protection
- Single AsyncModbusTcpClient keepalive, 50ms gap, qty <=125, sequential.
- Writes disabled for diagnostic entities by default (C/F/D/E/A/KG). Enable per entity only if you understand limits.
- Limits from knowledge.json "X bis Y" + type fallback; out-of-range writes blocked with log warning.
- `advanced_write: true` option in integration options to unlock hidden unsafe (default false).
- Throttle existing yaml +300 documented, backup kept.

## Versioning
manifest.json version + git tag `v0.1.0`. HACS tracks tags. Bump version on each release: update manifest.json + CHANGELOG + `git tag vX.Y.Z && git push origin tag`.
