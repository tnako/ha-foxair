#!/usr/bin/env python3
"""Fix translations: English default everywhere, German/RU complete, block headers translated."""
import json, pathlib, re
BASE = pathlib.Path(__file__).parents[1] / "custom_components/foxair"
regs = json.loads((BASE / "data/foxair_phnix_registers.json").read_text(encoding="utf-8-sig"))
meta = json.loads((BASE / "data/foxair_metadata.json").read_text(encoding="utf-8-sig"))

def load(p): return json.loads(p.read_text(encoding="utf-8-sig"))
strings = load(BASE / "strings.json")
en = load(BASE / "translations/en.json")
de = load(BASE / "translations/de.json")
ru = load(BASE / "translations/ru.json")

# --- helpers ---
def translate_block_to_en(german):
    """Translate Blockkopf German to English."""
    s = german
    replacements = [
        ("Blockkopf Paket Status", "Block Header Packet Status"),
        ("Blockkopf Paket", "Block Header Packet"),
        (" / Kennung Wort ", " ID Word "),
        (" / WiFi Barcode ASCII Zeichen ", " WiFi Barcode ASCII Char "),
        (" / ASCII Zeichen ", " ASCII Char "),
        (" / Reserve 1", " Reserved 1"),
        (" / Reserve 2", " Reserved 2"),
        (" / Reserve/Ende", " Reserved/End"),
        (" / Marker-Länge", " Marker Length"),
        (" / erstes Blockkopf-Register", " First Header Register"),
        (" / Status 1 / Reserve", " Status 1 / Reserved"),
        (" / Status 2 / Reserve", " Status 2 / Reserved"),
        (" – ", " - "),
        (" –", " -"),
    ]
    for germ, eng in replacements:
        s = s.replace(germ, eng)
    # Also handle "ASCII Reserve/Ende" case
    s = s.replace("ASCII Reserve/Ende", "ASCII Reserved/End")
    return s

# Explicit EN names for new/changed regs
EN_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Word 1/16",
    "201": "PHNIX/Aliyun ProductKey Word 2/16",
    "202": "PHNIX/Aliyun ProductKey Word 3/16",
    "203": "PHNIX/Aliyun ProductKey Word 4/16",
    "204": "PHNIX/Aliyun ProductKey Word 5/16",
    "205": "PHNIX/Aliyun ProductKey Word 6/16",
    "206": "PHNIX/Aliyun ProductKey Word 7/16",
    "207": "PHNIX/Aliyun ProductKey Word 8/16",
    "208": "PHNIX/Aliyun ProductKey Word 9/16",
    "209": "PHNIX/Aliyun ProductKey Word 10/16",
    "210": "PHNIX/Aliyun ProductKey Word 11/16",
    "211": "PHNIX/Aliyun ProductKey Word 12/16",
    "212": "PHNIX/Aliyun ProductKey Word 13/16",
    "213": "PHNIX/Aliyun ProductKey Word 14/16",
    "214": "PHNIX/Aliyun ProductKey Word 15/16",
    "215": "PHNIX/Aliyun ProductKey Word 16/16",
    "2125": "DHW Electric Energy High Word",
    "2126": "DHW Electric Energy Low Word",
    "2127": "DHW Thermal Energy High Word",
    "2128": "DHW Thermal Energy Low Word",
    "50043": "Service/OTA SSID (C37B)",
    "50044": "C37B Acknowledge Status",
    "50500": "Service/OTA SSID (C544)",
    "50501": "Hardware Code ASCII Word 1/4",
    "50502": "Hardware Code ASCII Word 2/4",
    "50503": "Hardware Code ASCII Word 3/4",
    "50504": "Hardware Code ASCII Word 4/4",
    "50505": "Hardware Version ASCII Word 1/2",
    "50506": "Hardware Version ASCII Word 2/2",
    "50507": "Software Code ASCII Word 1/4",
    "50508": "Software Code ASCII Word 2/4",
    "50509": "Software Code ASCII Word 3/4",
    "50510": "Software Code ASCII Word 4/4",
    "50511": "Internal Software Version ASCII Word 1/2",
    "50512": "Internal Software Version ASCII Word 2/2",
    "2136": "T04 Outdoor Temperature - Secondary Path",
    "2137": "Heat Pump Electrical Power (without booster)",
    "2138": "Heat Pump Thermal Power (without booster)",
    "2178": "Temperature/Humidity Sensor Temperature",
    "2179": "Relative Humidity",
    "2180": "Calculated Dew Point",
}
DE_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Wort 1/16",
    "201": "PHNIX/Aliyun ProductKey Wort 2/16",
    "202": "PHNIX/Aliyun ProductKey Wort 3/16",
    "203": "PHNIX/Aliyun ProductKey Wort 4/16",
    "204": "PHNIX/Aliyun ProductKey Wort 5/16",
    "205": "PHNIX/Aliyun ProductKey Wort 6/16",
    "206": "PHNIX/Aliyun ProductKey Wort 7/16",
    "207": "PHNIX/Aliyun ProductKey Wort 8/16",
    "208": "PHNIX/Aliyun ProductKey Wort 9/16",
    "209": "PHNIX/Aliyun ProductKey Wort 10/16",
    "210": "PHNIX/Aliyun ProductKey Wort 11/16",
    "211": "PHNIX/Aliyun ProductKey Wort 12/16",
    "212": "PHNIX/Aliyun ProductKey Wort 13/16",
    "213": "PHNIX/Aliyun ProductKey Wort 14/16",
    "214": "PHNIX/Aliyun ProductKey Wort 15/16",
    "215": "PHNIX/Aliyun ProductKey Wort 16/16",
    "2125": "Energiezähler elektrisch Warmwasser - High Word",
    "2126": "Energiezähler elektrisch Warmwasser - Low Word",
    "2127": "Energiezähler thermisch Warmwasser - High Word",
    "2128": "Energiezähler thermisch Warmwasser - Low Word",
    "50043": "Service-/OTA-SSID (C37B)",
    "50044": "C37B Quittungsstatus",
    "50500": "Service-/OTA-SSID (C544)",
    "50501": "Hardwarecode ASCII Wort 1/4",
    "50502": "Hardwarecode ASCII Wort 2/4",
    "50503": "Hardwarecode ASCII Wort 3/4",
    "50504": "Hardwarecode ASCII Wort 4/4",
    "50505": "Hardwareversion ASCII Wort 1/2",
    "50506": "Hardwareversion ASCII Wort 2/2",
    "50507": "Softwarecode ASCII Wort 1/4",
    "50508": "Softwarecode ASCII Wort 2/4",
    "50509": "Softwarecode ASCII Wort 3/4",
    "50510": "Softwarecode ASCII Wort 4/4",
    "50511": "Interne Softwareversion ASCII Wort 1/2",
    "50512": "Interne Softwareversion ASCII Wort 2/2",
    "2136": "T04 Außentemperatur - zweiter Veröffentlichungsweg",
    "2137": "Elektrische WP-/Inverterleistung ohne Zusatzanteil",
    "2138": "Thermische WP-Leistung ohne Zusatzanteil",
    "2178": "Temperatur des Temperatur-/Feuchtesensors",
    "2179": "Relative Luftfeuchtigkeit",
    "2180": "Berechneter Taupunkt",
}
RU_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Слово 1/16",
    "201": "PHNIX/Aliyun ProductKey Слово 2/16",
    "202": "PHNIX/Aliyun ProductKey Слово 3/16",
    "203": "PHNIX/Aliyun ProductKey Слово 4/16",
    "204": "PHNIX/Aliyun ProductKey Слово 5/16",
    "205": "PHNIX/Aliyun ProductKey Слово 6/16",
    "206": "PHNIX/Aliyun ProductKey Слово 7/16",
    "207": "PHNIX/Aliyun ProductKey Слово 8/16",
    "208": "PHNIX/Aliyun ProductKey Слово 9/16",
    "209": "PHNIX/Aliyun ProductKey Слово 10/16",
    "210": "PHNIX/Aliyun ProductKey Слово 11/16",
    "211": "PHNIX/Aliyun ProductKey Слово 12/16",
    "212": "PHNIX/Aliyun ProductKey Слово 13/16",
    "213": "PHNIX/Aliyun ProductKey Слово 14/16",
    "214": "PHNIX/Aliyun ProductKey Слово 15/16",
    "215": "PHNIX/Aliyun ProductKey Слово 16/16",
    "2125": "Счётчик эл. энергии ГВС старший",
    "2126": "Счётчик эл. энергии ГВС младший",
    "2127": "Счётчик тепл. энергии ГВС старший",
    "2128": "Счётчик тепл. энергии ГВС младший",
    "50043": "Service/OTA SSID (C37B)",
    "50044": "Статус подтверждения C37B",
    "50500": "Service/OTA SSID (C544)",
    "50501": "Код оборудования ASCII Слово 1/4",
    "50502": "Код оборудования ASCII Слово 2/4",
    "50503": "Код оборудования ASCII Слово 3/4",
    "50504": "Код оборудования ASCII Слово 4/4",
    "50505": "Версия оборудования ASCII Слово 1/2",
    "50506": "Версия оборудования ASCII Слово 2/2",
    "50507": "Код ПО ASCII Слово 1/4",
    "50508": "Код ПО ASCII Слово 2/4",
    "50509": "Код ПО ASCII Слово 3/4",
    "50510": "Код ПО ASCII Слово 4/4",
    "50511": "Внутр. версия ПО ASCII Слово 1/2",
    "50512": "Внутр. версия ПО ASCII Слово 2/2",
    "2136": "T04 Температура наружного воздуха — второй путь",
    "2137": "Эл. мощность теплового насоса (без догрева)",
    "2138": "Тепл. мощность теплового насоса (без догрева)",
    "2178": "Температура датчика влажности",
    "2179": "Относительная влажность",
    "2180": "Расчётная точка росы",
}

def ensure_domain(data, domain):
    if "entity" not in data: data["entity"]={}
    if domain not in data["entity"]: data["entity"][domain]={}
    return data["entity"][domain]

# Fix block headers and new regs
fixed = {"sensor":0, "number":0, "select":0, "total_en_leak":0, "added":0, "updated":0}
# Process all addrs in regs that are not BLOCK? Actually all including BLOCK need translation
# But we include all addrs except service 50043+ (excluded from poll) — but still fix if exists
# For sensor domain, all addrs should have entry; for number/select only editable

# First, fix sensor entries for all addrs (including BLOCK)
for addr_str, rec in regs.items():
    if addr_str.startswith("_"): continue
    addr = addr_str
    german_name = rec.get("name","")
    # Determine expected names
    if addr in EN_OVERRIDES:
        en_name = EN_OVERRIDES[addr]
        de_name = DE_OVERRIDES[addr]
        ru_name = RU_OVERRIDES[addr]
    elif rec.get("type")=="BLOCK":
        en_name = translate_block_to_en(german_name)
        de_name = german_name
        ru_name = en_name  # diagnostic fallback to English for RU
    else:
        # For other regs, keep existing EN if exists and not German leak, else translate
        # If not in overrides and not BLOCK, use existing en if present else German
        # Try to keep existing
        en_name = None
        de_name = german_name
        ru_name = None
        # Check existing
        key = f"foxair_{addr}"
        existing_en = en.get("entity",{}).get("sensor",{}).get(key,{}).get("name") or strings.get("entity",{}).get("sensor",{}).get(key,{}).get("name")
        if existing_en and "Blockkopf" not in existing_en and "Kennung" not in existing_en:
            # keep if not obviously German leak and not outdated candidate/reserved mismatch
            # Detect outdated for 2125 etc: if german is energy but en is Reserved -> need update, but that is covered by overrides
            en_name = existing_en
        else:
            # fallback: for non-block, just keep german as de, en as german translated via simple? Use german as en fallback but ideally English
            # For now, if not BLOCK and not override, keep german as en only if no better — but we have existing hack: if existing_en is German leak, translate block else keep german
            if rec.get("type")=="BLOCK":
                en_name = translate_block_to_en(german_name)
            else:
                # For regular regs that changed, we already handled via overrides; otherwise keep existing
                en_name = existing_en or german_name
        # ru fallback
        existing_ru = ru.get("entity",{}).get("sensor",{}).get(key,{}).get("name")
        if existing_ru and any(ord(c)>127 for c in existing_ru): # has Cyrillic
            ru_name = existing_ru
        else:
            ru_name = en_name

        # If we didn't decide, skip
        if en_name is None:
            continue

    # Now ensure entries in all files for sensor domain
    for data, name, lang in [(strings, en_name, "strings"), (en, en_name, "en"), (de, de_name, "de"), (ru, ru_name, "ru")]:
        domain_dict = ensure_domain(data, "sensor")
        key = f"foxair_{addr}"
        if key not in domain_dict:
            domain_dict[key] = {"name": name}
            fixed["added"]+=1
        else:
            if domain_dict[key].get("name") != name:
                # Only update if mismatch and lang is en/strings with German leak or override
                # For en/strings, update if German leak or override; for de/ru update accordingly
                should_update = False
                if lang in ("strings","en"):
                    if addr in EN_OVERRIDES or "Blockkopf" in domain_dict[key].get("name","") or "Kennung" in domain_dict[key].get("name",""):
                        should_update=True
                elif lang=="de":
                    if addr in DE_OVERRIDES or "Blockkopf" not in name: # de should be German, if en was German leak then de was correct, no need? but ensure de is German
                        if domain_dict[key].get("name") != name:
                            should_update=True
                elif lang=="ru":
                    if addr in RU_OVERRIDES or "Blockkopf" in domain_dict[key].get("name",""):
                        should_update=True
                if should_update:
                    domain_dict[key]["name"] = name
                    fixed["updated"]+=1

# Also ensure number and select domains are synced for editable entities
for addr_str, meta_rec in meta.items():
    platform = meta_rec.get("platform")
    if platform not in ("number","select"): continue
    if not meta_rec.get("editable"): continue
    key = f"foxair_{addr_str}"
    # Sensor name is source
    sensor_en = en["entity"]["sensor"].get(key,{}).get("name") or strings["entity"]["sensor"].get(key,{}).get("name") or meta_rec.get("name","")
    sensor_de = de["entity"]["sensor"].get(key,{}).get("name") or sensor_en
    sensor_ru = ru["entity"]["sensor"].get(key,{}).get("name") or sensor_en
    for domain in [platform]:
        for data, name in [(strings, sensor_en), (en, sensor_en), (de, sensor_de), (ru, sensor_ru)]:
            d = ensure_domain(data, domain)
            if key not in d:
                # Copy from sensor with same name
                d[key] = {"name": name}
                fixed[domain]+=1
            else:
                # ensure name matches sensor
                if d[key].get("name") != name:
                    # Keep existing to avoid overwriting manually translated? But ensure sync
                    # For number/select, names should match sensor
                    d[key]["name"] = name
                    fixed["updated"]+=1
            # Also ensure state for select copied? States are separate, keep existing states

# Also fix block headers that were missing in strings sensor but present in regs but we already added sensor entries above
# Additionally, ensure number/select translations for all languages have same structure as strings (top-level config/options)
# Ensure en translations mirror strings for config/options
# Validate select state completeness: keep as is

# Save
for path, data in [(BASE/"strings.json", strings), (BASE/"translations/en.json", en), (BASE/"translations/de.json", de), (BASE/"translations/ru.json", ru)]:
    # sort keys for deterministic output? keep original order but ensure json pretty
    # HA expects strings.json top-level order: config, entity, options
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"Fixed: {fixed}")
# validate
print(f"strings sensor: {len(strings['entity']['sensor'])} en sensor: {len(en['entity']['sensor'])} de sensor: {len(de['entity']['sensor'])} ru sensor: {len(ru['entity']['sensor'])}")
print(f"strings number: {len(strings['entity'].get('number',{}))} select: {len(strings['entity'].get('select',{}))}")
# check missing 2178
for addr in ["2178","2179","2180"]:
    for lang, data in [("strings", strings),("en",en),("de",de),("ru",ru)]:
        print(f"{lang}  {addr}: {data['entity']['sensor'].get(f'foxair_{addr}',{}).get('name')}")
# check block 1181
for addr in ["1181","2125","2136","200"]:
    for lang, data in [("strings", strings),("en",en)]:
        print(f"{lang} {addr}: {data['entity']['sensor'].get(f'foxair_{addr}',{}).get('name')}")
