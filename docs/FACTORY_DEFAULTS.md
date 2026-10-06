# Factory defaults and deliberate deviations

Reference for comparing a unit's settings with factory values, and a record of
which deviations on our test unit are intentional. The machine-readable values
live in `custom_components/foxair/data/foxair_factory_defaults.json`. The
integration never writes them on its own.

## How sure are these values?

There is no official FoxAir parameter list, and no public dump of a GL-9 in a
confirmed factory state. The JSON records, per value, which sources support it
and a confidence level, and leaves a value empty (`null`) where the FoxAir
sources disagree. Our own unit's values are never used as a source: they were
changed by hand.

| Key | Source | Unit | Factory state? |
| --- | --- | --- | --- |
| `gl15_reset` | photovoltaikforum [p126 #4892658](https://www.photovoltaikforum.com/thread/242531-foxair-w%C3%A4rmepumpen-erfahrungen-meinungen-tipps/?pageNo=126), creambox, 2026-10-01, WarmLink PW66 screenshots | FoxAir GL-15-1, firmware V3.4 | Yes, per the owner: "Ich habe alle Einstellungen auf Werkseinstellungen zurückgesetzt" (p120 #4888117) |
| `gl9_video` | [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) `data/foxair_phnix_registers.json`, `app_current_video_value`, screen recording 2026-06-14 | FoxAir GL9 | Unknown. One unit's current values; E02 = 3.0 shows tuning |
| `phnix_manual` | PHNIX-built R290 monoblock technical manuals, section 13 "Electrical Parameter", Default value column: [Kaisai KHX](https://www.m-klima.com/files/uploads/product_file/269-Technical-Manual-KHX---Heat-Pump-KAISAI-%EF%BC%88English%EF%BC%89.pdf.pdf) and [Cooper&Hunter Ecopower](https://cooperandhunter.de/wp-content/uploads/OM-Ecopower-EN.pdf), 2022 | Same controller, other brands | Yes, printed manufacturer defaults, but generic: both manuals print the identical table, it predates E03-x/E07-x, and FoxAir differs from it on 8 codes where both FoxAir units agree (E03, E07, E08, E10, E14, C10, C11, A06) |
| `display_fw` | Display firmware disassembly (DEMONS.ASM) as recorded in FoxAir_Control `data/foxair_phnix_knowledge.json` | Controller family | Yes for the few codes it covers (E03-1, E03-2, E07-4, E07-5, A31) |

Rule used: a value counts when the factory-reset FoxAir unit agrees with the
printed manual or with the second FoxAir unit. The manual alone does not
override FoxAir, because FoxAir ships its own profile.

Confidence levels in the JSON:

| Level | Meaning | Values |
| --- | --- | --- |
| `foxair_reset_and_manual` | Factory-reset FoxAir GL-15-1 and the printed PHNIX manual default agree | 43 |
| `foxair_two_units` | Factory-reset FoxAir GL-15-1 and the FoxAir GL9 recording agree (the generic manual may differ) | 15 |
| `firmware_and_unit` | Display firmware default and one FoxAir unit agree | 2 |
| `foxair_reset_only` | Only the factory-reset FoxAir GL-15-1; a differing manual value is listed as candidate | 14 |
| `gl9_video_and_manual` | FoxAir GL9 recording and the PHNIX manual agree; not on the reset unit | 1 |
| `manual_only` | Only the generic PHNIX manual; FoxAir may configure it differently | 3 |
| `gl9_video_only` | Only the FoxAir GL9 recording, whose tuning state is unknown | 5 |
| `conflict` | Sources disagree; value is null, see candidates | 8 |

Rejected as factory references: creambox's earlier GL-15-1 dump (p99
#4868784, the owner had already changed settings), rbxbr p45 (says the
screenshots deviate from factory in defrost, hysteresis and frequency), the
PHNIX Modbus protocol PDF (p7 #4289405, superseded by the printed manuals), and
any screenshot without a statement about its state.

Read with care:

- The model differs. GL-9 and GL-15 share the controller and compressor model
  code (C04 = 13), but their refrigerant circuits differ, and some values
  (likely E07-1/2/3, where the units disagree) are set per model.
- The GL-15-1 went from firmware V1.2 to V3.4 before the reset. A reset
  restores the defaults of the installed firmware.
- Method: all 133 thread pages were downloaded and every image attachment was
  read with local OCR (macOS Vision), then checked by hand where the OCR was
  ambiguous. Manual tables were extracted from the PDF text layer.

The way to get real GL-9 factory values is a screenshot from a GL-9 owner
directly after installation, or after "restore factory settings" on the
display, posted together with the firmware version. Add it as a source and
raise the confidence of the matching values.

## Our test unit (GL-9, firmware V3.5)

Read with `tools/modbus_probe.py` on 2026-10-06. Values are display values.

### EEV, before the 2026-10-06 change

On 2026-10-06 the EEV settings were written to E02 5.0, E07 60, E03-1..5
250/185/140/125/110 and E07-1..5 130/130/110/90/85, and made the efficiency
analyser baseline. Supported: E02 (reset unit + manual), E03-1..5, E07 and
E07-4 (two FoxAir units), E07-5 (firmware + GL9). Not proven: E07-1/2/3
(130/130/110 from the GL9 recording, 215/150/120 on the factory-reset GL-15;
the manual predates these codes). 130/130/110 was kept because it comes from a
GL9, the same model.

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| E02 | Target Superheat for Heating | 3.5 °C | 5 °C (gl9 3) | reset + manual |
| E07 | Min Initial Steps | 40 N | 60 N (manual 100) | 2 FoxAir units |
| E03-1 | EEV Initial Steps for Heating1 | 230 N | 250 N | 2 FoxAir units |
| E03-2 | EEV Initial Steps for Heating2 | 160 N | 185 N | 2 FoxAir units |
| E03-3 | EEV Initial Steps for Heating3 | 120 N | 140 N | 2 FoxAir units |
| E03-4 | EEV Initial Steps for Heating4 | 110 N | 125 N | 2 FoxAir units |
| E03-5 | EEV Initial Steps for Heating5 | 90 N | 110 N | 2 FoxAir units |
| E07-1 | EEV Min. Steps1 | 110 N | 215 N (reset) / 130 N (gl9) | conflict |
| E07-2 | EEV Min. Steps2 | 110 N | 150 N (reset) / 130 N (gl9) | conflict |
| E07-3 | EEV Min. Steps3 | 1 N | 120 N (reset) / 110 N (gl9) | conflict |
| E07-4 | EEV Min. Steps4 | 70 N | 90 N | 2 FoxAir units |
| E07-5 | EEV Min. Steps5 | 60 N | 85 N (reset 80) | firmware + unit |

E07-3 = 1 looked like a typo: it let the valve close almost fully at high
compressor speed with the outdoor temperature between -4.9 and 0 °C.

### Deliberate deviations kept (owner's choice)

Generated from a full read of 190 editable registers against the JSON, so it
covers every code the JSON lists. "Factory candidate" shows the value and, in
brackets, other sources that differ. The defrost changes are the owner's winter
efficiency tuning.

#### Defrost

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| D01 | Ambient Temp. of Starting Defrosting | 10 °C | 12.5 °C | reset + manual |
| D02 | Heating Operation Time Before Defrosting | 30 min | 26 min | reset + manual |
| D06 | Defrosting Cycle Time Correction | 15 | 5 (manual 15) | reset only |
| D11 | Min. Inlet Water Temp. of Defrosting | 12 °C | 23 °C | reset + manual |
| D12 | Suction Pressure of Forced Defrosting | 3.5 bar | 1 bar (manual 2) | reset only |
| D13 | Heating Operation Time Before Forced Defrosting | 150 min | 120 min | reset + manual |
| D17 | Coil Temp. of Exit Defrosting | 32 °C | 13 °C | reset + manual |
| D19 | Max. Defrosting Time | 16 min | 8 min | reset + manual |
| D20 | Defrosting Frequency | 68 Hz | 70 Hz | reset + manual |
| D21 | Enable Electric Heater During Defrosting | 0 | 1 | reset + manual |
| D25 | Max. Water Temp. Decrease during Defrosting | 38 °C | 7 °C | reset only |
| D30 | Button Heater Delays OFF Time after Defrost | 7 min | 0 min | reset only |

#### Fan

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| F02 | Max Cool Coil Temp | 42 °C | 35 °C (manual 50) | reset only |
| F03 | Min Cool Coil Temp | 22 °C | 10 °C | reset + manual |
| F05 | Max Heat Coil Temp | -4 °C | 2 °C (manual 10) | reset only |
| F06 | Min Heat Coil Temp | 10 °C | 20 °C | reset + manual |
| F19 | Min. Fan Speed in Heating | 200 rpm | 300 rpm | reset + manual |
| F23 | DC/AC Fan Rated Speed | 830 rpm | 600 rpm | reset + manual |
| F25 | Cooling Fan Max Speed | 580 rpm | 600 rpm (manual 700) | reset only |

#### Compressor

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| C02 | Min. Comp. Frequency | 27 Hz | 30 Hz (gl9 29) | reset + manual |
| C07 | Resonanzpunkt 1 | 20 Hz | 0 Hz (gl9 27) | reset + manual |
| C08 | Resonanzpunkt 2 | 22 Hz | 0 Hz | reset + manual |
| C09 | Resonanzpunkt 3 | 24 Hz | 0 Hz | reset + manual |
| C10 | Min. Comp. Frequency in Heating at Low Ambient T | 35 Hz | 40 Hz (manual 60) | 2 FoxAir units |
| C11 | Max. Comp. Frequency in Cooling at High Ambient  | 55 Hz | 72 Hz (manual 66) | 2 FoxAir units |

#### Protection and heaters

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| A03 | Shutdown Ambient Temp. | -30 °C | -25 °C | reset + manual |
| A04 | Antifreeze Temp. | -0.5 °C | 4 °C | reset + manual |
| A05 | Antifreeze Temp. Difference | 3.5 °C | 3 °C | reset + manual |
| A06 | Exhaust Temp Protect Setup | 90 °C | 110 °C (manual 115) | 2 FoxAir units |
| A22 | Niedrige Wassertemperatur Schutzwert | -2 °C | 4 °C (gl9 5) | reset + manual |
| A27 | Temp Difference A Of Limiting Frequency | 12 °C | 7 °C | reset + manual |
| A28 | Temp Diff between Outlet and DHW Temp | 4 °C | 7 °C | reset + manual |
| A33 | Electric Heater Opening Temp. Diff | 3.5 °C | 3 °C | GL9 video only |
| A34 | Crank Preheating Time | 7 min | 5 min | GL9 video only |

#### Water pump

| Code | Name | Unit (before) | Factory candidate | Confidence |
| --- | --- | --- | --- | --- |
| P01 | Main Circulation Pump Operation Mode | 1 | 2 | GL9 video + manual |
| P02 | Interval Time | 45 min | 30 min (gl9 35) | reset + manual |
| P05 | DHW Pump Operation Mode | 1 | 2 | GL9 video only |
| P11 | Target Temp. Diff. for Pump Speed Control | 3.5 °C | 5 °C (reset) / 4.4 °C (gl9) | conflict |

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
