#!/usr/bin/env python3
"""Generate per-bit binary_sensor translations for BITFIELD registers.

Reads bit_map (German) from foxair_phnix_registers.json, writes
foxair_<addr>_bit<N> keys and, for registers with a code, the
foxair_<code>_bit<N> keys the entities actually use (e.g. foxair_err04_bit7)
into strings.json + en/de/ru.json (+ icons).
de = bit_map label minus state annotations; en/ru from BIT_TEXT below.

Re-run after any bit_map change. Fails loudly on bits missing en/ru so
new registers cannot slip in untranslated. Reserved/unknown bits are
skipped (see const.BITFIELD_RESERVED_RE — must match).
Run: python3 tools/gen_bitfield_translations.py
"""
import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent / "custom_components/foxair"
sys.path.insert(0, str(BASE.parent.parent / "tools"))

# (addr, bit): (en, ru)
BIT_TEXT = {
    # 2139 frequency limiter status (FW V3.5)
    (2139, 1): ("Water spread limiter active (A24)", "Ограничение по разнице температур воды активно (A24)"),
    (2139, 3): ("Temperature difference limiter active (A27)", "Ограничение по разнице температур активно (A27)"),
    (2139, 4): ("Low-pressure frequency limiter active (A38)", "Ограничитель частоты по низкому давлению активен (A38)"),
    (2139, 5): ("Input current limiter active", "Ограничение по входному току активно"),
    (2139, 6): ("Discharge temperature limiter active (T12)", "Ограничение по температуре нагнетания активно (T12)"),
    # 2146 heating/summer cut-off status (FW V3.5)
    (2146, 4): ("Summer cut-off active", "Летнее откл. активно"),
    # 2088 bit 7: external outdoor sensor missing/invalid (1463 = 1, live V3.5)
    (2088, 0): ("ERR04 P182 Discharge temperature too high (3x latched)", "ERR04 P182 Слишком высокая температура нагнетания (3x)"),
    (2088, 7): ("External AT sensor fault", "Ошибка внешнего датчика"),
    # 2019 load outputs
    (2019, 0): ("Compressor actually running", "Компрессор работает"),
    (2019, 2): ("At least one fan actually running", "Вентилятор работает (хотя бы один)"),
    (2019, 3): ("Fan low-speed output", "Выход низкой скорости вентилятора"),
    (2019, 4): ("Water pump output", "Выход насоса воды"),
    (2019, 5): ("DHW pump output", "Выход насоса ГВС"),
    (2019, 6): ("4-way valve 1", "4-ходовой клапан 1"),
    (2019, 7): ("Electric heating stage 1", "Электронагрев ступень 1"),
    (2019, 8): ("Electric heating stage 2", "Электронагрев ступень 2"),
    (2019, 9): ("3-way valve", "3-ходовой клапан"),
    (2019, 10): ("Alarm output", "Выход аварии"),
    (2019, 11): ("Crankcase heater", "Подогрев картера"),
    (2019, 12): ("Drain pan heater", "Подогрев поддона"),
    (2018, 0): ("DHW tank electric heater", "Электронагреватель бака ГВС"),
    (2018, 8): ("Zone 1 pump output", "Выход насоса зоны 1"),
    (2018, 9): ("Zone 2 pump output", "Выход насоса зоны 2"),
    (2018, 10): ("3-way valve cooling", "3-ходовой клапан охлаждения"),
    # 2034 S01 switch states / SG Ready
    (2034, 0): ("S01 High-pressure switch", "S01 Реле высокого давления"),
    (2034, 1): ("S02 Low-pressure switch", "S02 Реле низкого давления"),
    (2034, 2): ("S03 Water flow switch", "S03 Реле протока воды"),
    (2034, 3): ("S04 Electric-heater overheat switch", "S04 Защита электронагрева от перегрева"),
    (2034, 4): ("S05 Remote on/off", "S05 Дистанционное вкл/выкл"),
    (2034, 5): ("S06 Remote heating/cooling", "S06 Дистанционно отопление/охлаждение"),
    (2034, 6): ("S07 DHW switch", "S07 Выключатель ГВС"),
    (2034, 9): ("S10 Heating/cooling on/off", "S10 Отопление/охлаждение вкл/выкл"),
    (2034, 12): ("SG contact 1 / remote switch / terminals 1-2", "SG контакт 1 / дистанционный выключатель / клеммы 1–2"),
    (2034, 13): ("SG contact 2 / PV contact / terminals 7-8", "SG контакт 2 / PV-контакт / клеммы 7–8"),
    # 2081 ERR07
    (2081, 0): ("ERR07 F00 IPM overcurrent fault", "ERR07 F00 Перегрузка IPM по току"),
    (2081, 1): ("ERR07 F01 Compressor driver fault", "ERR07 F01 Ошибка драйвера компрессора"),
    (2081, 2): ("ERR07 Compressor overcurrent", "ERR07 Перегрузка компрессора по току"),
    (2081, 3): ("ERR07 Input voltage phase loss", "ERR07 Потеря фазы входного напряжения"),
    (2081, 4): ("ERR07 IPM current sensing fault", "ERR07 Ошибка измерения тока IPM"),
    (2081, 5): ("ERR07 F26 IGBT overheating fault", "ERR07 F26 Перегрев IGBT"),
    (2081, 6): ("ERR07 Precharge fault", "ERR07 Ошибка предзаряда"),
    (2081, 7): ("ERR07 DC bus overvoltage", "ERR07 Перенапряжение DC-шины"),
    (2081, 8): ("ERR07 DC bus undervoltage", "ERR07 Пониженное напряжение DC-шины"),
    (2081, 9): ("ERR07 AC input undervoltage", "ERR07 Пониженное входное напряжение AC"),
    (2081, 10): ("ERR07 AC input overcurrent trip", "ERR07 Отключение по перегрузке входа AC"),
    (2081, 11): ("ERR07 Input voltage sensing fault", "ERR07 Ошибка измерения входного напряжения"),
    (2081, 12): ("ERR07 DSP-PFC communication fault", "ERR07 Ошибка связи DSP–PFC"),
    (2081, 13): ("ERR07 F17 Compressor driver temp sensor fault", "ERR07 F17 Ошибка датчика температуры драйвера компрессора"),
    (2081, 14): ("ERR07 F11 DSP-compressor driver communication fault", "ERR07 F11 Ошибка связи DSP–драйвер компрессора"),
    (2081, 15): ("ERR07 F151 Compressor driver-main board communication fault", "ERR07 F151 Ошибка связи драйвер компрессора–главная плата"),
    # 2082 ERR08
    (2082, 0): ("ERR08 IPM overheat stop", "ERR08 Останов по перегреву IPM"),
    (2082, 1): ("ERR08 F14 Compressor phase loss", "ERR08 F14 Обрыв фазы компрессора"),
    (2082, 3): ("ERR08 Input current sensing fault", "ERR08 Ошибка измерения входного тока"),
    (2082, 6): ("ERR08 EEPROM fault", "ERR08 Ошибка EEPROM"),
    (2082, 7): ("ERR08 F10 AC input overvoltage fault", "ERR08 F10 Перенапряжение входа AC"),
    (2082, 15): ("ERR08 Compressor overspeed protection", "ERR08 Защита компрессора от превышения оборотов"),
    # 2083 ERR09
    (2083, 0): ("ERR09 F33 Frequency reduced by compressor current", "ERR09 F33 Снижение частоты по току компрессора"),
    (2083, 1): ("ERR09 F16 Compressor weak magnetisation alarm", "ERR09 F16 Слабое намагничивание компрессора"),
    (2083, 2): ("ERR09 Power unit overheating", "ERR09 Перегрев силового блока"),
    (2083, 4): ("ERR09 F22 Frequency reduced by AC input current", "ERR09 F22 Снижение частоты по входному току AC"),
    (2083, 5): ("ERR09 EEPROM fault warning", "ERR09 Предупреждение об ошибке EEPROM"),
    (2083, 7): ("ERR09 F24 EEPROM damaged / invalid fault data", "ERR09 F24 EEPROM повреждена / неверные данные ошибок"),
    # 2084 ERR10 fan driver
    (2084, 8): ("ERR10 F120 Fan driver temp sensor fault", "ERR10 F120 Ошибка датчика температуры драйвера вентилятора"),
    (2084, 9): ("ERR10 F108 Fan driver IPM overheating", "ERR10 F108 Перегрев IPM драйвера вентилятора"),
    (2084, 10): ("ERR10 F105 Fan driver external overcurrent", "ERR10 F105 Внешняя перегрузка по току драйвера вентилятора"),
    (2084, 11): ("ERR10 F101 Fan driver supply phase loss", "ERR10 F101 Обрыв фазы питания драйвера вентилятора"),
    (2084, 12): ("ERR10 F112 Fan driver current sensing fault", "ERR10 F112 Ошибка измерения тока драйвера вентилятора"),
    (2084, 13): ("ERR10 F102 Fan driver start failure", "ERR10 F102 Ошибка запуска драйвера вентилятора"),
    (2084, 14): ("ERR10 F113 Fan driver internal overcurrent", "ERR10 F113 Внутренняя перегрузка по току драйвера вентилятора"),
    (2084, 15): ("ERR10 F109 Fan driver overspeed protection", "ERR10 F109 Защита драйвера вентилятора от превышения оборотов"),
    # 2085 ERR01
    (2085, 2): ("ERR01 Heating return temp sensor fault", "ERR01 Ошибка датчика температуры обратки отопления"),
    (2085, 3): ("ERR01 Heating outlet water temp sensor fault", "ERR01 Ошибка датчика температуры подачи отопления"),
    (2085, 4): ("ERR01 High-pressure protection", "ERR01 Защита по высокому давлению"),
    (2085, 5): ("ERR01 TC No cooling at low outdoor temperature", "ERR01 TC Нет охлаждения при низкой наружной температуре"),
    (2085, 6): ("ERR01 Low-pressure protection", "ERR01 Защита по низкому давлению"),
    (2085, 7): ("ERR01 E030 Insufficient water flow during defrost", "ERR01 E030 Недостаточный проток воды при разморозке"),
    (2085, 8): ("ERR01 E032 Flow switch fault", "ERR01 E032 Ошибка реле протока"),
    (2085, 9): ("ERR01 E04 Electric heater overheating", "ERR01 E04 Перегрев электронагревателя"),
    (2085, 10): ("ERR01 E19 Primary antifreeze fault", "ERR01 E19 Первичная защита от замерзания"),
    (2085, 11): ("ERR01 E29 Secondary antifreeze fault", "ERR01 E29 Вторичная защита от замерзания"),
    (2085, 12): ("ERR01 Antifreeze protection", "ERR01 Защита от замерзания"),
    (2085, 13): ("ERR01 E035 Low water flow protection", "ERR01 E035 Защита по низкому протоку воды"),
    (2085, 14): ("ERR01 P42 Room temp sensor fault", "ERR01 P42 Ошибка датчика комнатной температуры"),
    # 2086 ERR02
    (2086, 0): ("ERR02 P182 Discharge temperature too high", "ERR02 P182 Слишком высокая температура нагнетания"),
    (2086, 3): ("ERR02 E103 Fan motor 1 overload", "ERR02 E103 Перегрузка двигателя вентилятора 1"),
    (2086, 4): ("ERR02 E203 Fan motor 2 overload", "ERR02 E203 Перегрузка двигателя вентилятора 2"),
    (2086, 5): ("ERR02 Inlet/outlet water temp diff too large", "ERR02 Слишком большая разница температур воды вход/выход"),
    (2086, 6): ("ERR02 E065 Outlet water temp too high", "ERR02 E065 Слишком высокая температура воды на выходе"),
    (2086, 7): ("ERR02 Mixed-water outlet temp sensor fault", "ERR02 Ошибка датчика температуры смешанной воды на выходе"),
    (2086, 8): ("ERR02 DHW return temp sensor fault", "ERR02 Ошибка датчика температуры обратки ГВС"),
    (2086, 9): ("ERR02 DHW outlet temp sensor fault", "ERR02 Ошибка датчика температуры подачи ГВС"),
    (2086, 10): ("ERR02 P105 Zone 1 room temp sensor fault", "ERR02 P105 Ошибка датчика комнатной температуры зоны 1"),
    (2086, 11): ("ERR02 P106 Zone 2 room temp sensor fault", "ERR02 P106 Ошибка датчика комнатной температуры зоны 2"),
    (2086, 12): ("ERR02 P107 Zone 2 mixing temp sensor fault", "ERR02 P107 Ошибка датчика температуры смешения зоны 2"),
    (2086, 13): ("ERR02 E08g Zone 1 thermostat communication fault", "ERR02 E08g Ошибка связи с термостатом зоны 1"),
    (2086, 14): ("ERR02 E08h Zone 2 thermostat communication fault", "ERR02 E08h Ошибка связи с термостатом зоны 2"),
    (2086, 15): ("ERR02 E122 Mixing valve control fault", "ERR02 E122 Ошибка управления смесительным клапаном"),
    # 2087 ERR03 (3x latched)
    (2087, 4): ("ERR03 High-pressure protection (3x latched)", "ERR03 Защита по высокому давлению (3x)"),
    (2087, 6): ("ERR03 Low-pressure protection (3x latched)", "ERR03 Защита по низкому давлению (3x)"),
    (2087, 8): ("ERR03 E032 Flow switch fault (3x latched)", "ERR03 E032 Ошибка реле протока (3x)"),
    (2087, 9): ("ERR03 E04 Electric heater overheating (3x latched)", "ERR03 E04 Перегрев электронагревателя (3x)"),
    (2087, 10): ("ERR03 E035 Low water flow protection (3x latched)", "ERR03 E035 Защита по низкому протоку воды (3x)"),
    (2087, 12): ("ERR03 Antifreeze protection (3x latched)", "ERR03 Защита от замерзания (3x)"),
    # 2088 ERR04 (3x latched)
    (2088, 2): ("ERR04 Inlet/outlet water temp diff too large (3x latched)", "ERR04 Слишком большая разница температур воды (3x)"),
    (2088, 3): ("ERR04 Outlet water temp too low (3x latched)", "ERR04 Слишком низкая температура воды на выходе (3x)"),
    (2088, 4): ("ERR04 Outlet water overtemp protection (3x latched)", "ERR04 Защита от перегрева воды на выходе (3x)"),
    # 2089 ERR05 sensor faults
    (2089, 0): ("ERR05 Inlet water temp fault", "ERR05 Ошибка температуры воды на входе"),
    (2089, 1): ("ERR05 Outlet water temp fault", "ERR05 Ошибка температуры воды на выходе"),
    (2089, 2): ("ERR05 Coil temp fault", "ERR05 Ошибка температуры змеевика"),
    (2089, 3): ("ERR05 Ambient temp fault", "ERR05 Ошибка температуры воздуха"),
    (2089, 4): ("ERR05 Suction gas temp fault", "ERR05 Ошибка температуры всасываемого газа"),
    (2089, 5): ("ERR05 Antifreeze temp fault", "ERR05 Ошибка температуры защиты от замерзания"),
    (2089, 6): ("ERR05 P152 Manifold temp sensor fault", "ERR05 P152 Ошибка датчика температуры коллектора"),
    (2089, 7): ("ERR05 P03a Buffer tank temp sensor fault", "ERR05 P03a Ошибка датчика температуры буферной ёмкости"),
    (2089, 9): ("ERR05 EVI inlet temp fault", "ERR05 Ошибка температуры входа EVI"),
    (2089, 10): ("ERR05 EVI outlet temp fault", "ERR05 Ошибка температуры выхода EVI"),
    (2089, 11): ("ERR05 Discharge temp fault", "ERR05 Ошибка температуры нагнетания"),
    (2089, 12): ("ERR05 PP12 High-pressure sensor fault", "ERR05 PP12 Ошибка датчика высокого давления"),
    (2089, 13): ("ERR05 System 1 pressure sensor fault", "ERR05 Ошибка датчика давления системы 1"),
    (2089, 14): ("ERR05 Low ambient temp fault", "ERR05 Ошибка низкой температуры воздуха"),
    (2089, 15): ("ERR05 Outlet temp too-low protection", "ERR05 Защита от слишком низкой температуры на выходе"),
    # 2090 ERR06
    (2090, 8): ("ERR06 P03 DHW tank temp sensor fault", "ERR06 P03 Ошибка датчика температуры бака ГВС"),
    (2090, 11): ("ERR06 Fan 1 fault", "ERR06 Ошибка вентилятора 1"),
    (2090, 12): ("ERR06 Fan 2 fault", "ERR06 Ошибка вентилятора 2"),
    (2090, 13): ("ERR06 Main board - fan 1 comm fault", "ERR06 Ошибка связи главной платы с вентилятором 1"),
    (2090, 14): ("ERR06 E08c Hydraulic module communication fault", "ERR06 E08c Ошибка связи с гидромодулем"),
    (2090, 15): ("ERR06 Main board - fan 2 comm fault", "ERR06 Ошибка связи главной платы с вентилятором 2"),
}

RESERVED_RE = re.compile(r"reserv|unbekannt|unknown|spare|nicht belegt", re.I)
STATE_NOTE_RE = re.compile(r"\s*\((?:[^() Schmidt]*(?:AUS|EIN|active-high)[^()]*)\)\s*$")


def de_name(label):
    return STATE_NOTE_RE.sub("", label).strip()


def main():
    regs = json.loads((BASE / "data/foxair_phnix_registers.json").read_text(encoding="utf-8-sig"))
    meta = json.loads((BASE / "data/foxair_metadata.json").read_text(encoding="utf-8-sig"))
    expected = {}
    for addr_str, rec in regs.items():
        if not addr_str.isdigit():
            continue
        m = meta.get(addr_str, {})
        if (m.get("type") or "").upper() != "BITFIELD" or m.get("hidden") or m.get("editable"):
            continue
        for bit, label in ((rec.get("bit_map") or {}).items()):
            if RESERVED_RE.search(str(label)):
                continue
            key = (int(addr_str), int(bit))
            if key not in BIT_TEXT:
                sys.exit(f"FAIL: no en/ru text for addr {addr_str} bit {bit} ({label[:80]}) — add to BIT_TEXT")
            names = (de_name(str(label)),) + BIT_TEXT[key]
            expected[f"foxair_{addr_str}_bit{bit}"] = names
            code_slug = re.sub(r"[^a-z0-9]+", "_", (m.get("code") or "").lower()).strip("_")
            if code_slug:
                expected[f"foxair_{code_slug}_bit{bit}"] = names
    missing_table = sorted(set(BIT_TEXT) - {(int(a), int(b)) for a in regs for b in ((regs[a].get("bit_map") or {}) if a.isdigit() else {})})
    if missing_table:
        sys.exit(f"FAIL: stale BIT_TEXT entries with no register bit: {missing_table}")
    files = {"strings": BASE / "strings.json", "en": BASE / "translations/en.json",
             "de": BASE / "translations/de.json", "ru": BASE / "translations/ru.json"}
    for lang, path in files.items():
        d = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=collections.OrderedDict)
        ent = d.setdefault("entity", collections.OrderedDict())
        sec = ent.setdefault("binary_sensor", collections.OrderedDict())
        for k, names in sorted(expected.items()):
            sec[k] = {"name": {"strings": names[1], "en": names[1], "de": names[0], "ru": names[2]}[lang]}
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    icons = json.loads((BASE / "icons.json").read_text(), object_pairs_hook=collections.OrderedDict)
    isec = icons.setdefault("entity", collections.OrderedDict()).setdefault("binary_sensor", collections.OrderedDict())
    for k in sorted(expected):
        addr = k.split("_")[1]
        m = meta.get(addr) or next((v for v in meta.values()
                                    if re.sub(r"[^a-z0-9]+", "_", (v.get("code") or "").lower()).strip("_") == addr), {})
        tab = m.get("tab") or ""
        icon = {"ERR": "mdi:alert", "S": "mdi:electric-switch"}.get(tab, "mdi:toggle-switch")
        isec[k] = {"default": icon}
    (BASE / "icons.json").write_text(json.dumps(icons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {len(expected)} bit keys in 4 files + icons")


if __name__ == "__main__":
    main()
