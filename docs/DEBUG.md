# Help

## Seeing what happens

Add this to your `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.foxair: debug
```

To help troubleshooting, go to **Settings -> Devices -> FoxAir -> Download diagnostics**. The file contains the host address, poll statistics and a few raw values - no passwords.

## Why some controls are hidden

Changing compressor, fan or defrost values can stop your heat pump. Everyday settings like heating temperature and pump mode are visible. Installer settings (`C` compressor, `F` fan, `D` defrost, `E` EEV, `A` protection, `KG` timers) are hidden as **Diagnostic** and disabled by default. Enable a single entity only if you understand its limits.

## If you still use YAML Modbus

If you already poll the heat pump via `modbus_foxair.yaml`, keep it but let this integration do the work - two integrations polling fast at the same time can overload the small Modbus bridge. Our installer throttles the YAML intervals during testing and keeps a backup.
