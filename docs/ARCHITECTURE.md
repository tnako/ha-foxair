# Architecture — where a register change lands

One page for agents and contributors: read this instead of re-reading platform
code before adding or moving a register.

## Data flow

```
data/foxair_phnix_registers.json   names, type, value_map/app_values, bit_map,
                                   value_min_firmware, depends_on
data/foxair_phnix_knowledge.json   descriptions (build_metadata parses "a-b" ranges from them)
data/foxair_config.json            hidden / dead_ranges / isolated_addrs, blocks (labels = devices),
                                   types (scale/unit/platform), markers, overrides
        │  tools/build_metadata.py
        ▼
data/foxair_metadata.json          runtime truth per addr: platform, editable, risk,
                                   requires_expert, hidden, poll_tier, min/max, min_firmware,
                                   block/tab/group. Never edit by hand.
```

## Which entity a register becomes

| Metadata | Entity |
| --- | --- |
| `hidden` | none, never polled (hidden beats expert) |
| `min_firmware` above 2104 | none until the firmware is read and meets the gate |
| editable + type platform `number` | `number` (range = metadata min/max) |
| editable + `value_map` / select type | `select`; options = `app_values` (English) slugged, or `select.VIRTUAL_SG_MAP`; options in `value_min_firmware` are dropped and rejected on older firmware |
| read-only `BITFIELD` with `bit_map` | one `binary_sensor` per documented bit (`foxair_<code or addr>_bit<N>`) |
| read-only other | `sensor` |
| `format: bit_split` / `alias_switch` | per-bit switch/button / normal-mode switch |

Changing a register's platform (sensor to number) needs a translation under the
new platform key; keep the sensor one.

## Which device an entity lands on

`const.device_for_addr`: addrs in `markers.core_main_addrs` go on the main
"Heat Pump" device, everything else on the sub-device named by
`blocks.labels[tab or block]` (e.g. `HC` = Heating curve, `T_Live` = Live,
`A` = Protection/Limits). A block/tab without a label falls through to the main
device (validate.py fails on that). Keep the main device for the few controls a
user needs every day.

`requires_expert` comes from `blocks.expert_blocks` unless the override pins it;
`T`/`T_Live` and `core_non_expert_addrs` are always visible.

## Markers: the only way entity code finds registers

`climate.py`, `image.py`, `heating_curve.py` and `diagnostics.py` never contain
register numbers (validate.py enforces it for climate/image). They read:

| Marker | Used for |
| --- | --- |
| `status` | power, mode (1012), run status, compressor frequency, mode_values |
| `control_source` | H25 selector and the current/target sensor per value |
| `setpoints` | heating/cooling/DHW targets, limits, start/stop hysteresis |
| `heat_curve` | slope/offset/H36, live target 2014, effective AT 2048, `points` (V3.5 7-point curve), `mode_values` |
| `outdoor_sensor` | 1463 selector, external 2033, internal 2136, fault word/bit (2088 bit 7) |
| `summer_cutoff` | 1464 threshold, 1465 delay (min), 2146 status bit, hysteresis |

Runtime markers in `validate._RUNTIME_MARKERS` must be quick-tier and visible
without expert mode. Add a new marker for a new functional group rather than a
literal.

## Translations

- Register names: `entity.<platform>.foxair_<code or addr>.name` in strings.json
  + en/de/ru, with the `CODE: ` prefix when the register has a code.
- Select options: `...state.<slug>` for every offered option (validate.py
  `select-states`).
- Bits: `tools/gen_bitfield_translations.py` (en/ru in `BIT_TEXT`), writes both
  the addr and the code key.
- Image texts: `entity.image.foxair_heating_curve.state.*` plus `_TL_FALLBACK`
  in image.py.

## Adding a register from a firmware discovery

1. Read it live first: `tools/modbus_probe.py read <addr>` and, for writables,
   `tools/modbus_probe.py write <addr>=<v> --watch <effect addr> --restore`.
   Record the observed value/unit/effect; RE notes have been wrong before.
2. Registry + knowledge entry, config override (block/tab, expert, `min_firmware`,
   explicit min/max), marker if entity code needs it.
3. `python3 tools/build_metadata.py`, translations, icons, `task validate`.
4. Tests for the contract, `task pre_release`, CHANGELOG with the live evidence.
