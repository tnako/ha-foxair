#!/usr/bin/env python3
"""Generate per-bit binary_sensor translations for BITFIELD registers.

Reads bit_map (German) from foxair_phnix_registers.json, writes
foxair_<addr>_bit<N> keys into strings.json + en/de/ru.json (+ icons).
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
    (2019, 13): ("Heating water pump", "Насос отопления"),
    (2019, 14): ("Hydro module water-circuit electric heating", "Электронагрев водяного контура гидромодуля"),
    (2019, 15): ("Hydro module DHW-tank electric heating", "Электронагрев бака ГВС гидромодуля"),
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
    (2081, 0): ("ERR07 IPM overheating", "ERR07 Перегрев IPM"),
    (2081, 1): ("ERR07 Compressor start failure", "ERR07 Ошибка запуска компрессора"),
    (2081, 2): ("ERR07 Compressor overcurrent", "ERR07 Перегрузка компрессора по току"),
    (2081, 3): ("ERR07 Input voltage phase loss", "ERR07 Потеря фазы входного напряжения"),
    (2081, 4): ("ERR07 IPM current sensing fault", "ERR07 Ошибка измерения тока IPM"),
    (2081, 5): ("ERR07 Drive board overheat protection", "ERR07 Защита платы привода от перегрева"),
    (2081, 6): ("ERR07 Precharge fault", "ERR07 Ошибка предзаряда"),
    (2081, 7): ("ERR07 DC bus overvoltage", "ERR07 Перенапряжение DC-шины"),
    (2081, 8): ("ERR07 DC bus undervoltage", "ERR07 Пониженное напряжение DC-шины"),
    (2081, 9): ("ERR07 AC input undervoltage", "ERR07 Пониженное входное напряжение AC"),
    (2081, 10): ("ERR07 AC input overcurrent trip", "ERR07 Отключение по перегрузке входа AC"),
    (2081, 11): ("ERR07 Input voltage sensing fault", "ERR07 Ошибка измерения входного напряжения"),
    (2081, 12): ("ERR07 DSP-PFC communication fault", "ERR07 Ошибка связи DSP–PFC"),
    (2081, 13): ("ERR07 Drive board temperature fault", "ERR07 Ошибка температуры платы привода"),
    (2081, 14): ("ERR07 DSP-comm board fault", "ERR07 Ошибка связи DSP–плата коммуникации"),
    (2081, 15): ("ERR07 Main board communication fault", "ERR07 Ошибка связи главной платы"),
    # 2082 ERR08
    (2082, 0): ("ERR08 IPM overheat stop", "ERR08 Останов по перегреву IPM"),
    (2082, 1): ("ERR08 Compressor default phase", "ERR08 Штатная фаза компрессора"),
    (2082, 3): ("ERR08 Input current sensing fault", "ERR08 Ошибка измерения входного тока"),
    (2082, 6): ("ERR08 EEPROM fault", "ERR08 Ошибка EEPROM"),
    (2082, 7): ("ERR08 Input overvoltage limit protection", "ERR08 Защита от превышения входного напряжения"),
    (2082, 15): ("ERR08 Compressor overspeed protection", "ERR08 Защита компрессора от превышения оборотов"),
    # 2083 ERR09
    (2083, 0): ("ERR09 Current control frequency alarm", "ERR09 Авария частоты регулирования тока"),
    (2083, 1): ("ERR09 Compressor magnet protection alarm", "ERR09 Авария магнитной защиты компрессора"),
    (2083, 2): ("ERR09 Power unit overheating", "ERR09 Перегрев силового блока"),
    (2083, 4): ("ERR09 AC input current control alarm", "ERR09 Авария регулирования входного тока AC"),
    (2083, 5): ("ERR09 EEPROM fault warning", "ERR09 Предупреждение об ошибке EEPROM"),
    # 2085 ERR01
    (2085, 2): ("ERR01 Heating return temp sensor fault", "ERR01 Ошибка датчика температуры обратки отопления"),
    (2085, 3): ("ERR01 Heating outlet water temp sensor fault", "ERR01 Ошибка датчика температуры подачи отопления"),
    (2085, 4): ("ERR01 High-pressure protection", "ERR01 Защита по высокому давлению"),
    (2085, 6): ("ERR01 Low-pressure protection", "ERR01 Защита по низкому давлению"),
    (2085, 8): ("ERR01 Water flow protection", "ERR01 Защита по протоку воды"),
    (2085, 9): ("ERR01 Electric heating overload protection", "ERR01 Защита электронагрева от перегрузки"),
    (2085, 10): ("ERR01 Winter antifreeze stage 1", "ERR01 Зимняя защита от замерзания ступень 1"),
    (2085, 11): ("ERR01 Winter antifreeze stage 2", "ERR01 Зимняя защита от замерзания ступень 2"),
    (2085, 12): ("ERR01 Antifreeze protection", "ERR01 Защита от замерзания"),
    (2085, 14): ("ERR01 Room temperature fault", "ERR01 Ошибка комнатной температуры"),
    # 2086 ERR02
    (2086, 3): ("ERR02 Fan 1 overload speed limit", "ERR02 Ограничение оборотов вентилятора 1 при перегрузке"),
    (2086, 4): ("ERR02 Fan 2 overload speed limit", "ERR02 Ограничение оборотов вентилятора 2 при перегрузке"),
    (2086, 5): ("ERR02 Inlet/outlet water temp diff too large", "ERR02 Слишком большая разница температур воды вход/выход"),
    (2086, 6): ("ERR02 Outlet water overheated", "ERR02 Перегрев воды на выходе"),
    (2086, 7): ("ERR02 Mixed-water outlet temp sensor fault", "ERR02 Ошибка датчика температуры смешанной воды на выходе"),
    (2086, 8): ("ERR02 DHW return temp sensor fault", "ERR02 Ошибка датчика температуры обратки ГВС"),
    (2086, 9): ("ERR02 DHW outlet temp sensor fault", "ERR02 Ошибка датчика температуры подачи ГВС"),
    # 2087 ERR03 (3x latched)
    (2087, 4): ("ERR03 High-pressure protection (3x latched)", "ERR03 Защита по высокому давлению (3x)"),
    (2087, 6): ("ERR03 Low-pressure protection (3x latched)", "ERR03 Защита по низкому давлению (3x)"),
    (2087, 8): ("ERR03 Water flow protection (3x latched)", "ERR03 Защита по протоку воды (3x)"),
    (2087, 9): ("ERR03 Electric heating protection (3x latched)", "ERR03 Защита электронагрева (3x)"),
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
    (2089, 6): ("ERR05 Coil outlet water temp sensor fault", "ERR05 Ошибка датчика температуры воды на выходе змеевика"),
    (2089, 9): ("ERR05 EVI inlet temp fault", "ERR05 Ошибка температуры входа EVI"),
    (2089, 10): ("ERR05 EVI outlet temp fault", "ERR05 Ошибка температуры выхода EVI"),
    (2089, 11): ("ERR05 Discharge temp fault", "ERR05 Ошибка температуры нагнетания"),
    (2089, 13): ("ERR05 System 1 pressure sensor fault", "ERR05 Ошибка датчика давления системы 1"),
    (2089, 14): ("ERR05 Low ambient temp fault", "ERR05 Ошибка низкой температуры воздуха"),
    (2089, 15): ("ERR05 Outlet temp too-low protection", "ERR05 Защита от слишком низкой температуры на выходе"),
    # 2090 ERR06
    (2090, 8): ("ERR06 DHW temp fault", "ERR06 Ошибка температуры ГВС"),
    (2090, 11): ("ERR06 Fan 1 fault", "ERR06 Ошибка вентилятора 1"),
    (2090, 12): ("ERR06 Fan 2 fault", "ERR06 Ошибка вентилятора 2"),
    (2090, 13): ("ERR06 Main board - fan 1 comm fault", "ERR06 Ошибка связи главной платы с вентилятором 1"),
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
            expected[f"foxair_{addr_str}_bit{bit}"] = (de_name(str(label)),) + BIT_TEXT[key]
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
        m = meta.get(addr, {})
        tab = m.get("tab") or ""
        icon = {"ERR": "mdi:alert", "S": "mdi:electric-switch"}.get(tab, "mdi:toggle-switch")
        isec[k] = {"default": icon}
    (BASE / "icons.json").write_text(json.dumps(icons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {len(expected)} bit keys in 4 files + icons")


if __name__ == "__main__":
    main()
