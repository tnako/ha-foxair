# ha-foxair - Home Assistant FoxAir / PHNIX Heat Pump

Public HACS integration for FoxAir / PHNIX heat pumps via Modbus TCP (tested with EW11-host:8899).

- Bulk polling (5 frames, ~16 req/min) - no bus overload
- Full register map from [FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (573 regs, grouping identical to Control) - see Attribution
- Popular entities enabled by default, installer/unsafe hidden as diagnostic (disabled by default)
- Multilang EN (default) + DE + RU
- Keeps your existing `modbus: FoxAIR` yaml untouched (throttle it to +300s during test)

## Installation via HACS (recommended, HAOS compatible)

1. Ensure HACS is installed (https://hacs.xyz/docs/use/).
2. In Home Assistant go to HACS -> Integrations -> three dots (top right) -> Custom repositories.
3. Add repository URL `https://github.com/tnako/ha-foxair`, category `Integration`, Add.
4. Search HACS for `FoxAir`, Install, Restart Home Assistant.
5. Settings -> Devices & Services -> Add Integration -> FoxAir Heat Pump.
   Enter Host `EW11-host`, Port `8899`, Slave `1` (defaults match stock Warmlink bridge). Choose polling: Fast 10s (T live), Slow 60s (R/P), Static 300s.
6. Entities appear grouped by blocks (R Sollwerte, T Diagnose/Live, P Pumpe etc.) - same as FoxAir_Control. Popular safe entities enabled, installer/unsafe (C/F/D/E/A/KG) disabled by default under Diagnostic - enable per entity if needed.

Manual install (no HACS):
 Copy `custom_components/foxair` to `/config/custom_components/foxair` on HAOS host (Samba/SSH `scp -r custom_components/foxair root@HA-host:/usr/share/hassio/homeassistant/custom_components/`), Restart.

Throttle existing yaml during test (already done via SSH +300):
 `modbus_foxair.yaml` scan_interval 20->320 etc. with original kept as comment. Revert: `cp modbus_foxair.yaml.bak.1787829054 modbus_foxair.yaml && ha core restart`.

## Configuration

## Attribution

Register definitions (`foxair_phnix_registers.json`, `foxair_phnix_knowledge.json`), block grouping (`BLOCK_SHORT_DESCRIPTIONS`), scaling (`format_value_by_type`) and Modbus framing logic are derived from [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (data/, core/foxair_phnix_core.py, workers/standard_modbus_worker.py). Many thanks to the FoxAir_Control authors for reverse-engineering and curation. PDFs/manuals from that repo are NOT redistributed here.

## License

MIT - see LICENSE
