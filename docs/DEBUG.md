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

`custom_components.foxair` owns a single `pymodbus.AsyncModbusTcpClient` per gateway (host:port): every pump (config entry) behind the same gateway shares it and one lock (`coordinator._GATEWAYS`), so slave 1 and slave 2 never have overlapping requests on one RS485 bus. All I/O is serialized under `coordinator._lock` (the gateway's lock). The connection closes when the last pump on that gateway unloads.

Polling is tiered — `quick` every 30 s / `medium` every 120 s / `rare` every 300-600 s — and batched per address space (`max_span=90`/`max_gap=30`, split around `dead_ranges`; the unit returns at most 90 registers per read). A transient "No response received" every ~10 min is normal for the EW11 and is filtered from the log; only unexpected errors surface. Diagnostics `stats.batch_errors` counts failures per batch (`<start>x<count>`), `stats.short_reads` lists reads that returned fewer registers than requested, `stats.max_ms` is the slowest poll.

## Why some controls are hidden

Changing compressor, fan or defrost values can stop your heat pump. Everyday settings like heating temperature and pump mode are visible. Installer settings (`C` compressor, `F` fan, `D` defrost, `E` EEV, `A` protection, `KG` timers) are hidden as **Diagnostic** and disabled by default. Enable a single entity only if you understand its limits.
