# Factory defaults and deliberate deviations

Reference for comparing a unit's settings with the factory values, and a record
of which deviations on our test unit are intentional. The machine-readable
values live in `custom_components/foxair/data/foxair_factory_defaults.json`.
The integration never writes them on its own.

## Where the factory values come from

There is no official parameter list from FoxAir. The values come from WarmLink
app screenshots (installer password PW66) posted in the photovoltaikforum
thread [FoxAIR Wärmepumpen – Erfahrungen, Meinungen & Tipps](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/):

| Key in the JSON | Post | Unit | What it is |
| --- | --- | --- | --- |
| `gl9_full` | [p126 #4892658](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/?pageNo=126), creambox, 2026-10-01 | GL-9-1 | Full H/A/F/D/E/R/P/G/C dump after the owner reset everything to the original state |
| `gl15_same_compressor` | [p99 #4868784](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/?pageNo=99), creambox, 2026-09-04 | GL-15-1, fresh install | Same compressor model (C04 = 13) |
| `foxair_control` | [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) `data/foxair_phnix_registers.json`, `app_current_video_value` | GL9 | App screen recording, 2026-06-14 |

Cross-checks that agree where they overlap: rbxbr p45 #4596637 (C/D blocks),
asterisk p15 #4399180 (A/D/P blocks), Dennissss p109 #4879126 (D block).

Method: all 133 thread pages were downloaded, and every image attachment was
read with local OCR (macOS Vision). Values were checked against the
screenshots by hand where OCR was ambiguous.

### Known differences between the sources

| Code | GL-9 (`gl9_full`) | GL-15 (`gl15_same_compressor`) | FoxAir_Control | JSON uses |
| --- | --- | --- | --- | --- |
| E07-1 | 215 | 215 | 130 | 130 |
| E07-2 | 150 | 155 | 130 | 130 |
| E07-3 | 120 | 120 | 110 | 110 |
| E07-4 | 90 | 100 | 90 | 90 |
| E07-5 | 80 | 90 | 85 | 85 |
| F02 | 35 °C | 40 °C | | 35 °C |
| D20 | 70 Hz | 60 Hz | | 70 Hz |
| C11 | 72 Hz | 66 Hz | | 72 Hz |

E07-1 to E07-5 (EEV minimum steps above 61 Hz) differ between screenshots of
the same model family, so they may change with firmware or a service visit.
The JSON keeps the FoxAir_Control GL9 recording values because that is the
source the integration already uses, and lists the forum value as `alt`.
These steps only act above 61 Hz, so the difference rarely matters.

Values that depend on the installation, not the model, are not in the JSON:
setpoints (R01-R03, curve points), H05 cooling, H31 pump type, H36/H37, A40
rated flow, timers and SG Ready.

## Our test unit (GL-9, firmware V3.5)

Read with `tools/modbus_probe.py` on 2026-10-06. Values are display values.

### EEV: back to factory on 2026-10-06

All EEV settings were written to the GL-9 factory values (read back OK) and
set as the efficiency analyser baseline with "Set EEV baseline". Previous
values, for reference:

| Code | Before | Factory, now |
| --- | --- | --- |
| E02 target superheat | 3.5 °C | 5.0 °C |
| E07 min steps | 40 | 60 |
| E03-1 / E03-2 / E03-3 / E03-4 / E03-5 | 230 / 160 / 120 / 110 / 90 | 250 / 185 / 140 / 125 / 110 |
| E07-1 / E07-2 / E07-3 / E07-4 / E07-5 | 110 / 110 / 1 / 70 / 60 | 130 / 130 / 110 / 90 / 85 |

E07-3 = 1 looked like a typo: it let the valve close almost fully at high
compressor speed with the outdoor temperature between -4.9 and 0 °C.

### Deliberate deviations kept (owner's choice)

Everything below differs from the GL-9 factory values and is kept on purpose.
The defrost changes are the owner's winter efficiency tuning. The table is
generated from a full settings read (190 editable registers) against the JSON,
so every deviation is listed.

Defrost:

| Code | Meaning | Unit | Factory |
| --- | --- | --- | --- |
| D01 | Ambient temperature to allow defrost | 10.0 °C | 12.5 °C |
| D02 | Heating time before the first defrost | 30 min | 26 min |
| D06 | Defrost cycle time correction | 15 min | 5 min |
| D11 | Min. inlet water temperature for defrost | 12.0 °C | 23.0 °C |
| D12 | Suction pressure for forced defrost | 3.5 bar | 1.0 bar |
| D13 | Heating time before forced defrost | 150 min | 120 min |
| D17 | Coil temperature to end defrost | 32.0 °C | 13.0 °C |
| D19 | Max. defrost time | 16 min | 8 min |
| D20 | Compressor frequency during defrost | 68 Hz | 70 Hz |
| D21 | Electric heater during defrost | No | Yes |
| D25 | Max. water temperature drop during defrost | 38.0 °C | 7.0 °C |
| D30 | Bottom heater off delay after defrost | 7 min | 0 min |

Fan:

| Code | Meaning | Unit | Factory |
| --- | --- | --- | --- |
| F02 | Coil temp. for max. fan speed, cooling | 42.0 °C | 35.0 °C |
| F03 | Coil temp. for min. fan speed, cooling | 22.0 °C | 10.0 °C |
| F05 | Coil temp. for max. fan speed, heating | -4.0 °C | 2.0 °C |
| F06 | Coil temp. for min. fan speed, heating | 10.0 °C | 20.0 °C |
| F19 | Min. fan speed, heating | 200 rpm | 300 rpm |
| F23 | Rated DC fan motor speed | 830 rpm | 600 rpm |
| F25 | Max. fan speed, cooling | 580 rpm | 600 rpm |

F26 stays at the factory 600 rpm. On this unit it can't go above 660 rpm.

Compressor:

| Code | Meaning | Unit | Factory |
| --- | --- | --- | --- |
| C02 | Min. compressor frequency | 27 Hz | 30 Hz |
| C07 / C08 / C09 | Resonance points (skipped frequencies) | 20 / 22 / 24 Hz | 0 / 0 / 0 Hz |
| C10 | Min. frequency in heating at low ambient | 35 Hz | 40 Hz |
| C11 | Max. frequency in cooling at high ambient | 55 Hz | 72 Hz |

Protection and heaters:

| Code | Meaning | Unit | Factory |
| --- | --- | --- | --- |
| A03 | Shutdown ambient temperature | -30.0 °C | -25.0 °C |
| A04 | Antifreeze temperature | -0.5 °C | 4.0 °C |
| A05 | Antifreeze temperature difference | 3.5 °C | 3.0 °C |
| A06 | Max. exhaust temperature | 90.0 °C | 110.0 °C |
| A22 | Min. antifreeze temperature | -2.0 °C | 4.0 °C |
| A27 | Temperature difference of limiting frequency | 12.0 °C | 7.0 °C |
| A28 | Temperature difference outlet vs DHW | 4.0 °C | 7.0 °C |
| A31 | Electric heater on below ambient | -8.0 °C | 7.0 °C |
| A32 | Electric heater delay after compressor start | 60 min | 30 min |
| A33 | Electric heater on temperature difference | 3.5 °C | 2.0 °C |
| A34 | Crankcase preheating time | 7 min | 0 min |

A04 and A22 below 0 °C are only safe with antifreeze (glycol) in the water
circuit. Check this before copying them to another installation.

Water pump and control:

| Code | Meaning | Unit | Factory |
| --- | --- | --- | --- |
| P02 | Pump interval in Saving mode | 45 min | 30 min |
| P10 | Pump speed (manual) | 0 % | 100 % |
| P11 | Pump target temperature difference | 3.5 °C | 5.0 °C |
| P12 | Pump speed adjust per period | 2 N | 4 N |
| H25 | Control temperature | Inlet water | Outlet water |
| R05 | Stop heating above target by | 6.0 °C | 1.0 °C |

R05 belongs to the control setup (H25 inlet regulation), not to the model.

P10 = 0 % means the pump speed comes from P11 control (PWM wire moved to P1-DO,
as described in the forum thread), not a fixed speed. P11 stays at 3.5 °C on
purpose: 5.0 °C trips the low-flow error on this installation. With A40 =
1.1 m³/h the pump must first hold more than 1.32 m³/h for 10 minutes before
speed control starts, then never drops below 0.88 m³/h.

## Keeping this page current

- Check a unit against the JSON: read the codes with `tools/modbus_probe.py`
  and compare by code. Mind the raw scaling: D05-x are tenths of a bar (raw 13 =
  1.3 bar), D14/D15 are hundredths (raw 130 = 1.30).
- New forum screenshots of another model: add a model block to the JSON with
  its own `match` (C04, refrigerant) and sources. Don't mix models in one block.
- When a deliberate deviation on the test unit changes, update the tables
  above in the same commit.
