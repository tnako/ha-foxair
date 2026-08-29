# Help

## Seeing what happens

Add this to your `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.foxair: debug
    modbus_connection: debug
```

To help troubleshooting, go to **Settings -> Devices -> FoxAir -> Download diagnostics**. The file contains the host address, poll statistics and a few raw values - no passwords.

## v0.4 Modbus

`custom_components.foxair` now owns a `ModbusConnection(ModbusTcpParams(host,port))` via `modbus_connection.pymodbus` (pip `modbus-connection[pymodbus]>=4.8`, HA ≥2026.3). Polling is `await foxair.async_update()` pooled per space (`max_span=45`/`max_gap=8`) instead of 12 manual `POLL_BLOCKS`. Config flow probes via a short-lived owned `ModbusConnection` (no HA `modbus` integration yet — that moves to `async_get_unit`/`async_get_temporary_unit` in v0.5 on HA 2026.9+).

## Why some controls are hidden

Changing compressor, fan or defrost values can stop your heat pump. Everyday settings like heating temperature and pump mode are visible. Installer settings (`C` compressor, `F` fan, `D` defrost, `E` EEV, `A` protection, `KG` timers) are hidden as **Diagnostic** and disabled by default. Enable a single entity only if you understand its limits.

## If you still use YAML Modbus

If you already poll the heat pump via `modbus_foxair.yaml`, keep it but let this integration do the work - two integrations polling fast at the same time can overload the small Modbus bridge. Our installer throttles the YAML intervals during testing and keeps a backup.
