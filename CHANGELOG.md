## 0.2.4
- fix translations: all 573 entity names now English in strings.json/en.json (replaces remaining German like Abgastemperatur, Auslasswassertemperatur, Niederdruck, etc.)
- fix orphan devices: auto-cleanup legacy per-block devices (foxair_H, foxair_A…) left from <0.2.3 - they appeared as 11 unavailable "FoxAir Modbus Heat Pump" devices
- ru.json synced to English fallback (was German) so Russian UI no longer shows German names
- BLOCK_SHORT labels translated to English

# Changelog

## 0.2.3 - 2026-08-27
- Fix: back to 1 device (was 20 devices per block) - grouping via name prefix [R01]/[T01] like Control

## 0.2.2 - 2026-08-27
- Fix climate SyntaxError, blocking file, Modbus storm

## 0.2.1 - 2026-08-27
- Friendly names + block grouping

## 0.2.0 - 2026-08-27
- Full bulk + climate
