# Factory defaults and deliberate deviations

Reference for comparing a unit's settings with factory values, and a record of
which deviations on our test unit are intentional. The machine-readable values
live in `custom_components/foxair/data/foxair_factory_defaults.json`. The
integration never writes them on its own.

## How sure are these values?

There is no official FoxAir parameter list, and no public dump of a GL-9 in its
factory state has turned up. The JSON therefore records candidates with a
confidence level per value, and leaves a value empty (`null`) where the
sources disagree.

| Key | Source | Unit | Factory state? |
| --- | --- | --- | --- |
| `gl15_reset` | photovoltaikforum [p126 #4892658](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/?pageNo=126), creambox, 2026-10-01, WarmLink PW66 screenshots | GL-15-1, same controller family | Yes, per the owner: "Ich habe alle Einstellungen auf Werkseinstellungen zurückgesetzt" (p120 #4888117) and "auf den ursprünglichen Zustand zurückgesetzt" (p126) |
| `gl9_video` | [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) `data/foxair_phnix_registers.json`, `app_current_video_value`, screen recording 2026-06-14 | GL9 | Unknown. These are one unit's current values, not labelled as factory, and E02 = 3.0 suggests tuning |
| `phnix_protocol` | PHNIX "MODBUS RTU PROTOCOL" V1.2 (2022-03-18), Default column, posted at [p7 #4289405](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/?pageNo=7) | Generic controller | Firmware defaults before model configuration (C04 = 0, F26 = 700 rpm, E07 = 100), so only a tie-breaker |
| `display_fw` | Display firmware disassembly (DEMONS.ASM) as recorded in FoxAir_Control `data/foxair_phnix_knowledge.json` | Controller family | Yes for the few codes it covers (E03-1, E03-2, E07-4, E07-5, A31): the value is compiled into the firmware |

Confidence levels in the JSON:

| Level | Meaning | Values |
| --- | --- | --- |
| `display_fw_confirmed` | Display firmware default and at least one unit screenshot agree | 5 |
| `two_units` | The factory-reset GL-15-1 and the GL9 recording show the same value | 17 |
| `gl15_reset_and_protocol` | Factory-reset GL-15-1 and the PHNIX protocol agree; not seen on a GL-9 | 22 |
| `gl15_reset_only` | Only the factory-reset GL-15-1 | 8 |
| `gl9_video_only` | Only the GL9 recording (tuning state unknown) | 4 |
| `conflict` | Sources disagree; `value` is null, see `candidates` | 15 |

Rejected as factory references: creambox's earlier GL-15-1 dump (p99
#4868784, the owner says he had already changed settings), rbxbr p45
(says the screenshots deviate from factory in defrost, hysteresis and
frequency), and any screenshot without a statement about its state.

Read with care:

- The model differs. GL-9 and GL-15 share the controller and compressor model
  code (C04 = 13), but their refrigerant circuits differ, and some values may
  be set per model at the factory.
- The GL-15-1 had a firmware update from V1.2 to V3.4 before the reset. A reset
  restores the defaults of the installed firmware, which may not match what a
  GL-9 shipped with.
- Method: all 133 thread pages were downloaded and every image attachment was
  read with local OCR (macOS Vision), then checked by hand where the OCR was
  ambiguous.

The way to get real GL-9 factory values is a screenshot from a GL-9 owner
directly after installation, or after "restore factory settings" on the
display, posted together with the firmware version. Add it as a source and
raise the confidence of the matching values.

## Our test unit (GL-9, firmware V3.5)

Read with `tools/modbus_probe.py` on 2026-10-06. Values are display values.

### EEV, before the 2026-10-06 change

On 2026-10-06 the EEV settings were written to E02 5.0, E07 60, E03-1..5
250/185/140/125/110 and E07-1..5 130/130/110/90/85, and made the efficiency
analyser baseline. Supported: E03-1..5, E07 and E07-4/E07-5 (two units or the
display firmware). Not proven: E02 (5.0 from the factory-reset GL-15 and the
protocol, 3.0 on the GL9 recording) and E07-1/2/3 (130/130/110 from the GL9
recording, 215/150/120 on the factory-reset GL-15).

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| E02 | Target Superheat for Heating | 3.5 °C | 5 °C (gl15) / 3 °C (gl9) / 5 °C (phnix) | conflict |
| E03-1 | EEV Initial Steps for Heating1 | 230 N | 250 N | firmware + unit |
| E03-2 | EEV Initial Steps for Heating2 | 160 N | 185 N | firmware + unit |
| E03-3 | EEV Initial Steps for Heating3 | 120 N | 140 N | 2 units |
| E03-4 | EEV Initial Steps for Heating4 | 110 N | 125 N | 2 units |
| E03-5 | EEV Initial Steps for Heating5 | 90 N | 110 N | 2 units |
| E07 | Min Initial Steps | 40 N | 60 N | 2 units |
| E07-1 | EEV Min. Steps1 | 110 N | 215 N (gl15) / 130 N (gl9) | conflict |
| E07-2 | EEV Min. Steps2 | 110 N | 150 N (gl15) / 130 N (gl9) | conflict |
| E07-3 | EEV Min. Steps3 | 1 N | 120 N (gl15) / 110 N (gl9) | conflict |
| E07-4 | EEV Min. Steps4 | 70 N | 90 N | firmware + unit |
| E07-5 | EEV Min. Steps5 | 60 N | 85 N | firmware + unit |

E07-3 = 1 looked like a typo: it let the valve close almost fully at high
compressor speed with the outdoor temperature between -4.9 and 0 °C.

### Deliberate deviations kept (owner's choice)

Generated from a full read of 190 editable registers against the JSON, so it
covers every code the JSON lists. "Factory candidate" shows all candidates
where the sources disagree. The defrost changes are the owner's winter
efficiency tuning.

#### Defrost

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| D01 | Ambient Temp. of Starting Defrosting | 10 °C | 12.5 °C | GL-15 reset + protocol |
| D02 | Heating Operation Time Before Defrosting | 30 min | 26 min | GL-15 reset + protocol |
| D06 | Defrosting Cycle Time Correction | 15 | 5 | GL-15 reset |
| D11 | Min. Inlet Water Temp. of Defrosting | 12 °C | 23 °C | GL-15 reset + protocol |
| D12 | Suction Pressure of Forced Defrosting | 3.5 bar | 1 bar | GL-15 reset |
| D13 | Heating Operation Time Before Forced Defrosting | 150 min | 120 min | GL-15 reset + protocol |
| D17 | Coil Temp. of Exit Defrosting | 32 °C | 13 °C | GL-15 reset + protocol |
| D19 | Max. Defrosting Time | 16 min | 8 min | GL-15 reset + protocol |
| D20 | Defrosting Frequency | 68 Hz | 70 Hz | GL-15 reset + protocol |
| D21 | Enable Electric Heater During Defrosting | 0 | 1 | GL-15 reset + protocol |
| D25 | Max. Water Temp. Decrease during Defrosting | 38 °C | 7 °C | GL-15 reset + protocol |
| D30 | Button Heater Delays OFF Time after Defrost | 7 min | 0 min | GL-15 reset |

#### Fan

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| F05 | Max Heat Coil Temp | -4 °C | 2 °C | GL-15 reset |
| F06 | Min Heat Coil Temp | 10 °C | 20 °C | GL-15 reset + protocol |
| F19 | Min. Fan Speed in Heating | 200 rpm | 300 rpm | GL-15 reset + protocol |
| F23 | DC/AC Fan Rated Speed | 830 rpm | 600 rpm | GL-15 reset + protocol |

#### Compressor

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| C02 | Min. Comp. Frequency | 27 Hz | 30 Hz (gl15) / 29 Hz (gl9) / 30 Hz (phnix) | conflict |
| C07 | Resonanzpunkt 1 | 20 Hz | 0 Hz (gl15) / 27 Hz (gl9) | conflict |
| C08 | Resonanzpunkt 2 | 22 Hz | 0 Hz | 2 units |
| C09 | Resonanzpunkt 3 | 24 Hz | 0 Hz | 2 units |
| C10 | Min. Comp. Frequency in Heating at Low Ambient T | 35 Hz | 40 Hz | 2 units |

#### Water pumprotection and heaters

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| A03 | Shutdown Ambient Temp. | -30 °C | -25 °C | 2 units |
| A04 | Antifreeze Temp. | -0.5 °C | 4 °C | 2 units |
| A05 | Antifreeze Temp. Difference | 3.5 °C | 3 °C | 2 units |
| A06 | Exhaust Temp Protect Setup | 90 °C | 110 °C | 2 units |
| A22 | Niedrige Wassertemperatur Schutzwert | -2 °C | 4 °C (gl15) / 5 °C (gl9) / 4 °C (phnix) | conflict |
| A27 | Temp Difference A Of Limiting Frequency | 12 °C | 7 °C | 2 units |
| A28 | Temp Diff between Outlet and DHW Temp | 4 °C | 7 °C | 2 units |
| A33 | Electric Heater Opening Temp. Diff | 3.5 °C | 3 °C | GL9 video |
| A34 | Crank Preheating Time | 7 min | 5 min | GL9 video |

#### Water pump

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| P02 | Interval Time | 45 min | 30 min (gl15) / 35 min (gl9) / 30 min (phnix) | conflict |
| P11 | Target Temp. Diff. for Pump Speed Control | 3.5 °C | 5 °C (gl15) / 4.4 °C (gl9) | conflict |

F26 stays at 600 rpm; on this unit it can't go above 660 rpm. P11 stays at
3.5 °C on purpose: 5.0 °C trips the low-flow error on this installation (with
A40 = 1.1 m³/h the pump must hold more than 1.32 m³/h for 10 minutes before
speed control starts, then never drops below 0.88 m³/h). P10 = 0 % because the
pump PWM wire is moved to P1-DO, so speed comes from P11 control.

A04 and A22 below 0 °C are only safe with antifreeze (glycol) in the water
circuit. Check this before copying them to another installation.

Not in the JSON, because they depend on the installation rather than the
model: setpoints and curve (R), H05, H25, H31, H36/H37, A40, timers, SG Ready.
On the test unit H25 = inlet water and R05 = 6.0 °C.

## Keeping this page current

- Compare a unit by code with the JSON. Mind the raw scaling: D05-x are tenths
  of a bar (raw 13 = 1.3 bar), D14/D15 are hundredths (raw 130 = 1.30).
- New source: add it under `sources`, then re-derive each value's
  `confidence`. Never mix models in one block; add a new model block with its
  own `match`.
- When a deliberate deviation on the test unit changes, update the tables above
  in the same commit.
