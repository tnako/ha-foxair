# ha-foxair - Home Assistant FoxAir / PHNIX Heat Pump

Public HACS integration for FoxAir / PHNIX heat pumps via Modbus TCP (tested with EW11-host:8899).

- Bulk polling (5 frames, ~16 req/min) - no bus overload
- Full register map from [FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (573 regs, grouping identical to Control) - see Attribution
- Popular entities enabled by default, installer/unsafe hidden as diagnostic (disabled by default)
- Multilang EN (default) + DE + RU
- Keeps your existing `modbus: FoxAIR` yaml untouched (throttle it to +300s during test)

Install via HACS: Add custom repository `tnako/ha-foxair` -> Integration -> FoxAir

## Attribution

Register definitions (`foxair_phnix_registers.json`, `foxair_phnix_knowledge.json`), block grouping (`BLOCK_SHORT_DESCRIPTIONS`), scaling (`format_value_by_type`) and Modbus framing logic are derived from [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (data/, core/foxair_phnix_core.py, workers/standard_modbus_worker.py). Many thanks to the FoxAir_Control authors for reverse-engineering and curation. PDFs/manuals from that repo are NOT redistributed here.

## License

MIT - see LICENSE
