# Help

## Seeing what happens

Add this to your `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.foxair: debug
```

To help troubleshooting, go to **Settings -> Devices -> FoxAir -> Download diagnostics**. The file contains the host address, poll statistics and a few raw values - no passwords.

## Modbus

`custom_components.foxair` owns a single `pymodbus.AsyncModbusTcpClient` (the EW11 gateway allows only one TCP client). All I/O is serialized under `coordinator._lock`.

Polling is tiered — `quick` every 30 s / `medium` every 120 s / `rare` every 300-600 s — and batched per address space (`max_span=45`/`max_gap=8`, split around `dead_ranges`). A transient "No response received after 3 retries" every ~10 min is normal for the EW11 and is filtered from the log; only unexpected errors surface.

## Why some controls are hidden

Changing compressor, fan or defrost values can stop your heat pump. Everyday settings like heating temperature and pump mode are visible. Installer settings (`C` compressor, `F` fan, `D` defrost, `E` EEV, `A` protection, `KG` timers) are hidden as **Diagnostic** and disabled by default. Enable a single entity only if you understand its limits.
